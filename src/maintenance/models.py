from simple_history.models import HistoricalRecords
from django.core.validators import FileExtensionValidator
from django.db import models
from django.conf import settings
from core.models import BaseModel
from inventory.models import Asset

class MaintenanceType(models.TextChoices):
    PREVENTIVE = 'PREVENTIVE', 'Mantenimiento Preventivo'
    CORRECTIVE = 'CORRECTIVE', 'Reparación / Correctivo'
    WARRANTY = 'WARRANTY', 'Garantía'
    DECOMMISSION = 'DECOMMISSION', 'Baja Definitiva (Desecho/Pérdida/Obsolescencia)'

class MaintenanceStatus(models.TextChoices):
    OPEN = 'OPEN', 'Abierto / En Diagnóstico'
    IN_PROGRESS = 'IN_PROGRESS', 'En Proceso / Con Proveedor'
    COMPLETED = 'COMPLETED', 'Completado / Resuelto'
    CANCELLED = 'CANCELLED', 'Cancelado'

class MaintenanceRecord(BaseModel):
    history = HistoricalRecords()
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='maintenances', verbose_name="Activo Tecnológico")
    type = models.CharField(max_length=20, choices=MaintenanceType.choices, verbose_name="Tipo de Evento")
    status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, default=MaintenanceStatus.OPEN, verbose_name="Estado del Ticket")
    description = models.TextField(verbose_name="Descripción del Problema o Motivo")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Reportado/Gestionado por")
    provider = models.CharField(max_length=150, blank=True, null=True, verbose_name="Proveedor o Técnico Externo")
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name="Costo Total (COP)")
    resolution_notes = models.TextField(blank=True, null=True, verbose_name="Notas de Resolución o Diagnóstico")

    class Meta:
        verbose_name = "Mantenimiento / Baja"
        verbose_name_plural = "Mantenimientos y Bajas"
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list("asset_id", flat=True).first()
            if previous is not None and previous != self.asset_id:
                raise ValidationError({"asset": "No se puede trasladar un ticket existente a otro activo."})

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        from django.db import router, transaction
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            Asset.objects.using(using).select_for_update().get(pk=self.asset_id)
            previous = type(self).objects.using(using).filter(pk=self.pk).values_list("asset_id", flat=True).first()
            if previous is not None and previous != self.asset_id:
                raise ValidationError({"asset": "No se puede trasladar un ticket existente a otro activo."})
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_type_display()} - {self.asset.asset_tag}"


from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from inventory.models import Asset

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from inventory.models import Asset

class MaintenanceDocument(models.Model):
    history = HistoricalRecords()
    maintenance = models.ForeignKey(MaintenanceRecord, on_delete=models.CASCADE, related_name="documents")
    document = models.FileField(
        upload_to="maintenance_docs/%Y/%m/",
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
        verbose_name="Acta / Evidencia",
        help_text="⚠️ ATENCIÓN: Solo se admite formato PDF. (Máximo 3 archivos)"
    )

    class Meta:
        verbose_name = "Documento Adjunto"
        verbose_name_plural = "Documentos Adjuntos"
