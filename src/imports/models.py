from django.db import models
from core.models import BaseModel

class ImportStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pendiente'
    APPROVED = 'APPROVED', 'Aprobado para Importar'
    IMPORTED = 'IMPORTED', 'Importado a Producción'
    REJECTED = 'REJECTED', 'Descartado'

class StagingAsset(BaseModel):
    """Tabla temporal para revisar y limpiar datos antes de pasarlos al inventario real"""
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
    validation_notes = models.TextField(blank=True, null=True, help_text="Errores detectados (ej. serial duplicado)")

    def __str__(self):
        return f"{self.sheet_name} Fila {self.row_number} - {self.legacy_asset_tag or 'Sin Placa'}"
