from simple_history.models import HistoricalRecords
from django.db import models
from core.models import BaseModel
from organizations.models import Company, Site

class AssetGroup(models.TextChoices):
    COMPUTING = 'COMPUTING', 'Cómputo'
    PERIPHERALS = 'PERIPHERALS', 'Periféricos'
    NETWORK = 'NETWORK', 'Red y comunicaciones'
    TELEPHONY = 'TELEPHONY', 'Telefonía'
    OTHER = 'OTHER', 'Otros'


class Category(BaseModel):
    history = HistoricalRecords()
    name = models.CharField('Nombre', max_length=100, unique=True)
    description = models.TextField('Descripción', blank=True, null=True)
    group = models.CharField('Grupo', max_length=20, choices=AssetGroup.choices, blank=True)

    class Meta:
        verbose_name = 'Tipo de activo'
        verbose_name_plural = 'Tipos de activo'

    def __str__(self):
        return self.name

class Brand(BaseModel):
    history = HistoricalRecords()
    name = models.CharField('Nombre', max_length=100, unique=True)

    class Meta:
        verbose_name = "marca"
        verbose_name_plural = "marcas"

    def __str__(self):
        return self.name

class ModelAsset(BaseModel):
    history = HistoricalRecords()
    brand = models.ForeignKey(Brand, verbose_name='Marca', on_delete=models.PROTECT, related_name='models', null=True, blank=True)
    category = models.ForeignKey(Category, verbose_name='Tipo de activo', on_delete=models.PROTECT, related_name='models', null=True, blank=True)
    name = models.CharField("Nombre", max_length=100)

    class Meta:
        verbose_name = "modelo"
        verbose_name_plural = "modelos"

    def __str__(self):
        return self.name

class AssetStatus(models.TextChoices):
    IN_MAINTENANCE = 'IN_MAINTENANCE', 'En Mantenimiento/Garantía'
    DECOMMISSIONED = 'DECOMMISSIONED', 'Dado de Baja'
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
    history = HistoricalRecords()

    asset_tag = models.CharField('Código interno', max_length=50, unique=True, blank=True, help_text="Generado al guardar: ACE-0001 o SOL-0001, según la propietaria.")
    legacy_asset_tag = models.CharField('Placa de activo fijo', max_length=50, blank=True, null=True, help_text="Identificador principal, opcional y único cuando existe.")
    serial_number = models.CharField('Número de serie', max_length=100, blank=True, null=True)
    
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='assets', verbose_name='Tipo de activo')
    brand = models.ForeignKey(Brand, verbose_name='Marca', on_delete=models.PROTECT, related_name='assets', null=True, blank=True)
    model = models.ForeignKey(ModelAsset, verbose_name='Modelo', on_delete=models.PROTECT, related_name='assets', null=True, blank=True)
    
    company = models.ForeignKey(Company, verbose_name='Compañía administradora', on_delete=models.PROTECT, related_name='assets_managed', help_text="Compañía que lo administra")
    owner_company = models.ForeignKey(Company, verbose_name='Compañía propietaria', on_delete=models.PROTECT, related_name='assets_owned', help_text="Compañía dueña", null=True, blank=True)
    site = models.ForeignKey(Site, verbose_name='Ciudad / ubicación física', on_delete=models.PROTECT, related_name='assets', null=True, blank=True)
    
    status = models.CharField('Estado', max_length=20, choices=AssetStatus.choices, default=AssetStatus.AVAILABLE)
    property_type = models.CharField('Tipo de propiedad', max_length=20, choices=PropertyType.choices, default=PropertyType.OWNED)
    
    purchase_date = models.DateField('Fecha de compra', blank=True, null=True)
    warranty_end_date = models.DateField('Fin de garantía', blank=True, null=True)
    observations = models.TextField('Observaciones', blank=True, null=True)

    class Meta:
        verbose_name = 'Activo'
        verbose_name_plural = 'Inventario de activos'
        constraints = [
            models.UniqueConstraint(
                fields=['legacy_asset_tag'],
                condition=models.Q(legacy_asset_tag__isnull=False) & ~models.Q(legacy_asset_tag=''),
                name='unique_legacy_asset_tag_if_exists',
            ),
            models.UniqueConstraint(
                fields=['serial_number'], 
                condition=models.Q(serial_number__isnull=False) & ~models.Q(serial_number=''), 
                name='unique_serial_number_if_exists'
            )
        ]

    def clean(self):
        super().clean()
        from .identification import validate_identity
        validate_identity(self)
        from organizations.validation import validate_company_links
        validate_company_links(self)
        from django.db import router
        from maintenance.services import validate_asset_status
        validate_asset_status(self, self._state.db or router.db_for_write(type(self), instance=self))

    def save(self, *args, **kwargs):
        from django.db import router, transaction
        from maintenance.services import validate_asset_status
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = Asset.objects.using(using).select_for_update().filter(pk=self.pk).first()
            from .identification import prepare_identity
            prepare_identity(self, previous, using, kwargs.get('update_fields'))
            if previous is not None and previous.status == AssetStatus.DECOMMISSIONED:
                from django.core.exceptions import ValidationError
                raise ValidationError("El activo dado de baja es de solo consulta.")
            fields = kwargs.get("update_fields")
            if fields is None or "status" in fields:
                validate_asset_status(self, using)
            from organizations.validation import save_with_company_links
            return save_with_company_links(self, super().save, *args, **kwargs)

    def __str__(self):
        return f"{self.display_identifier} · {self.asset_tag}" if self.legacy_asset_tag else self.asset_tag

    @property
    def display_identifier(self):
        return self.legacy_asset_tag or self.asset_tag

class AssetSpecs(BaseModel):
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        from .locking import save_asset_attachment
        return save_asset_attachment(self, super().save, *args, **kwargs)

    def __str__(self):
        return f"Especificaciones de {self.asset.asset_tag if hasattr(self, 'asset') else 'Activo'}"
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='specs')
    ram = models.CharField(max_length=50, blank=True, null=True)
    storage = models.CharField(max_length=50, blank=True, null=True)
    processor = models.CharField(max_length=100, blank=True, null=True)
    operating_system = models.CharField(max_length=100, blank=True, null=True)

class AssetNetwork(BaseModel):
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        from .locking import save_asset_attachment
        return save_asset_attachment(self, super().save, *args, **kwargs)

    def __str__(self):
        return f"Red de {self.asset.asset_tag if hasattr(self, 'asset') else 'Activo'}"
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='network')
    hostname = models.CharField( max_length=100, blank=True, null=True)
    mac_address = models.CharField(max_length=50, blank=True, null=True)
    imei = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    operator = models.CharField(max_length=50, blank=True, null=True)

class AssetWarranty(BaseModel):
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        from .locking import save_asset_attachment
        return save_asset_attachment(self, super().save, *args, **kwargs)

    def __str__(self):
        return f"Garantía de {self.asset.asset_tag if hasattr(self, 'asset') else 'Activo'}"
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='warranties')
    supplier = models.CharField(max_length=150, blank=True, null=True)
    purchase_date = models.DateField('Fecha de compra', blank=True, null=True)
    warranty_start = models.DateField(blank=True, null=True)
    warranty_end = models.DateField(blank=True, null=True)
    observations = models.TextField('Observaciones', blank=True, null=True)

class DecommissionedAsset(Asset):
    class Meta:
        proxy = True
        verbose_name = "Activo en Baja (Histórico)"
        verbose_name_plural = "Activos en Baja (Histórico)"


# --- AUDITORÍA DE USUARIOS ISO 27001 ---
from django.contrib.auth import get_user_model
from simple_history import register as history_register

try:
    User = get_user_model()
    history_register(User, app='inventory', m2m_fields=['groups', 'user_permissions'])
except Exception:
    pass
