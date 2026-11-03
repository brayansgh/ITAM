from django.db import models
from django.conf import settings
from core.models import BaseModel
from inventory.models import Asset
from employees.models import Employee

class AssignmentStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Vigente / En Custodia'
    RETURNED = 'RETURNED', 'Devuelto'
    TRANSFERRED = 'TRANSFERRED', 'Transferido a otro usuario'

class Assignment(BaseModel):
    # Relaciones protegidas contra borrado intencional (ISO 27001 A.8.1.1)
    asset = models.ForeignKey(
        Asset, 
        on_delete=models.PROTECT, 
        related_name='assignments',
        verbose_name="Activo Tecnológico"
    )
    employee = models.ForeignKey(
        Employee, 
        on_delete=models.PROTECT, 
        related_name='assignments',
        verbose_name="Empleado Responsable"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='created_assignments',
        verbose_name="Asignado por (TI)"
    )
    
    # Trazabilidad temporal
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Entrega")
    returned_at = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de Devolución")
    
    # Estado de la asignación y custodia
    status = models.CharField(
        max_length=20, 
        choices=AssignmentStatus.choices, 
        default=AssignmentStatus.ACTIVE,
        verbose_name="Estado"
    )
    
    # Evidencia técnica y condiciones físicas
    initial_condition = models.TextField(
        help_text="Estado físico y funcional del equipo al momento de la entrega",
        verbose_name="Condición de Entrega"
    )
    return_condition = models.TextField(
        blank=True, null=True, 
        help_text="Estado físico y funcional del equipo al momento de la devolución",
        verbose_name="Condición de Devolución"
    )
    
    observations = models.TextField(blank=True, null=True, verbose_name="Observaciones / Pérdida / Daños")
    
    # Almacenamiento del Acta PDF generada (Para no repudio)
    signed_act_pdf = models.FileField(
        upload_to='actas_firmadas/%Y/%m/', 
        blank=True, null=True, 
        verbose_name="Acta de Entrega (PDF)"
    )

    class Meta:
        verbose_name = "Asignación de Activo"
        verbose_name_plural = "Asignaciones de Activos"
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.asset.asset_tag} -> {self.employee.full_name} ({self.get_status_display()})"
