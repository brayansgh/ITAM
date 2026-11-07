from django.db import models
from core.models import BaseModel
from organizations.models import Company, Site, Area
from simple_history.models import HistoricalRecords

class DocumentType(models.TextChoices):
    CC = 'CC', 'Cédula de Ciudadanía'
    CE = 'CE', 'Cédula de Extranjería'
    PASSPORT = 'PASSPORT', 'Pasaporte'
    NIT = 'NIT', 'NIT'

class EmployeeStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Activo'
    INACTIVE = 'INACTIVE', 'Inactivo'
    RETIRO = 'RETIRO', 'Retiro de la compañía'

class Employee(BaseModel):
    history = HistoricalRecords()
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='employees', verbose_name="Compañía")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='employees', null=True, blank=True,
                             verbose_name="Ubicación física")
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name='employees', null=True, blank=True,
                             verbose_name="Área")

    document_type = models.CharField("Tipo de documento", max_length=10, choices=DocumentType.choices,
                                     default=DocumentType.CC)
    document_number = models.CharField("Número de documento", max_length=50, blank=True, null=True)
    full_name = models.CharField("Nombre completo", max_length=255)
    email = models.EmailField("Correo electrónico", blank=True, null=True)
    phone = models.CharField("Teléfono", max_length=50, blank=True, null=True)
    status = models.CharField("Estado", max_length=10, choices=EmployeeStatus.choices, default=EmployeeStatus.ACTIVE)
    created_at = models.DateTimeField("Fecha de registro", auto_now_add=True)
    updated_at = models.DateTimeField("Última actualización", auto_now=True)

    class Meta:
        verbose_name = "empleado"
        verbose_name_plural = "empleados"
        constraints = [
            models.UniqueConstraint(
                fields=['document_number'], 
                condition=models.Q(document_number__isnull=False) & ~models.Q(document_number=''), 
                name='unique_document_number_if_exists'
            )
        ]

    def clean(self):
        super().clean()
        from organizations.validation import validate_company_links
        validate_company_links(self)

    def save(self, *args, **kwargs):
        from organizations.validation import save_with_company_links
        return save_with_company_links(self, super().save, *args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.company.code})"

class RetiredEmployee(Employee):

    class Meta:
        proxy = True
        verbose_name = "Empleado retirado"
        verbose_name_plural = "Empleados retirados"
