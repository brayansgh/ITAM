from simple_history.models import HistoricalRecords
from django.db import models
from core.models import BaseModel

class ImportStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pendiente'
    APPROVED = 'APPROVED', 'Aprobado para Importar'
    IMPORTED = 'IMPORTED', 'Importado a Producción'
    REJECTED = 'REJECTED', 'Descartado'

class StagingAsset(BaseModel):
    history = HistoricalRecords()
    batch_id = models.UUIDField(null=True, blank=True, editable=False, db_index=True)
    workbook_data = models.JSONField(default=dict, editable=False, blank=True)
    import_reference = models.CharField(max_length=100, blank=True, editable=False)
    sheet_name = models.CharField(max_length=50)
    row_number = models.IntegerField()
    employee_name = models.CharField(max_length=255, blank=True, null=True)
    employee_document = models.CharField(max_length=50, blank=True, null=True)
    element = models.CharField(max_length=100, blank=True, null=True)
    legacy_asset_tag = models.CharField(max_length=50, blank=True, null=True)
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    brand = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=100, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    site = models.CharField(max_length=100, blank=True, null=True)
    area = models.CharField(max_length=100, blank=True, null=True)
    ram = models.CharField(max_length=50, blank=True, null=True)
    storage = models.CharField(max_length=50, blank=True, null=True)
    processor = models.CharField(max_length=100, blank=True, null=True)
    operating_system = models.CharField(max_length=100, blank=True, null=True)
    hostname = models.CharField(max_length=100, blank=True, null=True)
    mac_address = models.CharField(max_length=50, blank=True, null=True)
    observations = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=ImportStatus.choices, default=ImportStatus.PENDING)
    validation_notes = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['import_reference'],
                condition=models.Q(status=ImportStatus.IMPORTED) & ~models.Q(import_reference=''),
                name='unique_published_asset_import_reference',
            ),
        ]

    def __str__(self):
        return f"{self.sheet_name} Fila {self.row_number} - {self.legacy_asset_tag or 'Sin Placa'}"
