from simple_history.models import HistoricalRecords
from django.db import models
from django.conf import settings
from core.models import BaseModel
from inventory.models import Asset
from employees.models import Employee


class AssignmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Vigente / En Custodia"
    RETURNED = "RETURNED", "Devuelto"
    TRANSFERRED = "TRANSFERRED", "Transferido a otro usuario"


class Assignment(BaseModel):
    history = HistoricalRecords()
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name="Activo Tecnológico",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name="Empleado Responsable",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assignments",
        verbose_name="Asignado por (TI)",
    )
    assigned_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de Entrega",
    )
    returned_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha de Devolución",
    )
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE,
        verbose_name="Estado",
    )
    initial_condition = models.TextField(
        help_text="Estado físico y funcional del equipo al momento de la entrega",
        verbose_name="Condición de Entrega",
    )
    return_condition = models.TextField(
        blank=True,
        null=True,
        help_text="Estado físico y funcional del equipo al momento de la devolución",
        verbose_name="Condición de Devolución",
    )
    observations = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observaciones / Pérdida / Daños",
    )
    signed_act_pdf = models.FileField(
        upload_to="actas_firmadas/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Acta de Entrega (PDF)",
    )

    class Meta:
        verbose_name = "Historial de Asignación"
        verbose_name_plural = "Historial de Asignaciones"
        ordering = ["-assigned_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["asset"],
                condition=models.Q(status=AssignmentStatus.ACTIVE),
                name="unique_active_assignment_per_asset",
            ),
        ]

    def _validate_new_custody(self, using, lock=False):
        if self.status != AssignmentStatus.ACTIVE or self.employee_id is None:
            return
        previous = type(self).objects.using(using).filter(pk=self.pk).values("status", "employee_id").first()
        if previous and previous["status"] == AssignmentStatus.ACTIVE and previous["employee_id"] == self.employee_id:
            return
        from employees.validation import validate_assignment_recipient
        employees = Employee.objects.using(using)
        if lock:
            employees = employees.select_for_update()
        employee = employees.filter(pk=self.employee_id).first()
        if employee is not None:
            validate_assignment_recipient(employee)

    def clean(self):
        super().clean()
        from django.db import router
        self._validate_new_custody(self._state.db or router.db_for_write(type(self), instance=self))

    def save(self, *args, **kwargs):
        from django.db import router, transaction
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        fields = kwargs.get("update_fields")
        with transaction.atomic(using=using):
            if self.status == AssignmentStatus.ACTIVE and (fields is None or {"status", "employee", "employee_id"}.intersection(fields)):
                Asset.objects.using(using).select_for_update().filter(pk=self.asset_id).first()
                self._validate_new_custody(using, lock=True)
            return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.asset.asset_tag} -> "
            f"{self.employee.full_name} "
            f"({self.get_status_display()})"
        )


# Modelo Proxy para crear una vista agrupada por usuario sin duplicar tablas
class EmployeeAssetSummary(Employee):
    class Meta:
        proxy = True
        verbose_name = "Resumen por Usuario"
        verbose_name_plural = "2. Resumen por Usuarios"


# Modelo para actas de devolución
class OffboardingRecord(BaseModel):
    history = HistoricalRecords()
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="offboarding_records",
        verbose_name="Empleado",
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_offboarding_records",
        verbose_name="Recibido por",
    )

    observations = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observaciones generales",
    )

    pdf = models.FileField(
        upload_to="actas_desvinculacion/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="Acta de devolución",
    )

    class Meta:
        verbose_name = "Acta de devolución"
        verbose_name_plural = "Actas de devolución"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Acta de {self.employee.full_name} - {self.created_at:%d/%m/%Y}"


class OffboardingRecordItem(BaseModel):
    history = HistoricalRecords()
    offboarding_record = models.ForeignKey(
        OffboardingRecord,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Acta",
    )

    assignment = models.OneToOneField(
        Assignment,
        on_delete=models.PROTECT,
        related_name="offboarding_item",
        verbose_name="Asignación devuelta",
    )

    condition = models.TextField(
        verbose_name="Condición del activo",
    )

    observations = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observaciones del activo",
    )

    class Meta:
        verbose_name = "Activo recibido en devolución"
        verbose_name_plural = "Activos recibidos en devolución"

    def __str__(self):
        return (
            f"{self.assignment.asset.asset_tag} - "
            f"{self.offboarding_record.employee.full_name}"
        )
