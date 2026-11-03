from django.db import models
from core.models import BaseModel
from organizations.models import Company, Site

class Category(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Brand(BaseModel):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Model(BaseModel):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='models')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='models', null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.brand.name} {self.name}"

class AssetStatus(models.TextChoices):
    AVAILABLE = 'AVAILABLE', 'Disponible'
    ASSIGNED = 'ASSIGNED', 'Asignado'
    MAINTENANCE = 'MAINTENANCE', 'En Mantenimiento'
    RETIRED = 'RETIRED', 'Retirado'
    LOST = 'LOST', 'Perdido'
    IN_TRANSIT = 'IN_TRANSIT', 'En Tránsito'

class PropertyType(models.TextChoices):
    OWNED = 'OWNED', 'Propio'
    LEASED = 'LEASED', 'Arrendado'
    THIRD_PARTY = 'THIRD_PARTY', 'Terceros'

class Asset(BaseModel):
    asset_tag = models.CharField(max_length=50, unique=True, help_text="Código interno único (ej. ACT-000001)")
    legacy_asset_tag = models.CharField(max_length=50, blank=True, null=True, help_text="Placa heredada del Excel")
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='assets')
    model = models.ForeignKey(Model, on_delete=models.PROTECT, related_name='assets', null=True, blank=True)
    
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='assets_managed', help_text="Compañía que lo administra")
    owner_company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='assets_owned', help_text="Compañía dueña", null=True, blank=True)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='assets', null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=AssetStatus.choices, default=AssetStatus.AVAILABLE)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices, default=PropertyType.OWNED)
    
    purchase_date = models.DateField(blank=True, null=True)
    warranty_end_date = models.DateField(blank=True, null=True)
    observations = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['serial_number'], 
                condition=models.Q(serial_number__isnull=False) & ~models.Q(serial_number=''), 
                name='unique_serial_number_if_exists'
            )
        ]

    def __str__(self):
        return f"{self.asset_tag} - {self.category.name}"

class AssetSpecs(BaseModel):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='specs')
    ram = models.CharField(max_length=50, blank=True, null=True)
    storage = models.CharField(max_length=50, blank=True, null=True)
    processor = models.CharField(max_length=100, blank=True, null=True)
    operating_system = models.CharField(max_length=100, blank=True, null=True)

class AssetNetwork(BaseModel):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='network')
    hostname = models.CharField(max_length=100, blank=True, null=True)
    mac_address = models.CharField(max_length=50, blank=True, null=True)
    imei = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    operator = models.CharField(max_length=50, blank=True, null=True)

class AssetWarranty(BaseModel):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='warranties')
    supplier = models.CharField(max_length=150, blank=True, null=True)
    purchase_date = models.DateField(blank=True, null=True)
    warranty_start = models.DateField(blank=True, null=True)
    warranty_end = models.DateField(blank=True, null=True)
    observations = models.TextField(blank=True, null=True)
