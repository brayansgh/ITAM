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
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='employees')
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='employees', null=True, blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, related_name='employees', null=True, blank=True)
    
    document_type = models.CharField(max_length=10, choices=DocumentType.choices, default=DocumentType.CC)
    document_number = models.CharField(max_length=50, blank=True, null=True)
    
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    
    status = models.CharField(
    max_length=10,
    choices=EmployeeStatus.choices,
    default=EmployeeStatus.ACTIVE
)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['document_number'], 
                condition=models.Q(document_number__isnull=False) & ~models.Q(document_number=''), 
                name='unique_document_number_if_exists'
            )
        ]

    def __str__(self):
        return f"{self.full_name} ({self.company.code})"

class RetiredEmployee(Employee):

    class Meta:
        proxy = True
        verbose_name = "Empleado retirado"
        verbose_name_plural = "Empleados retirados"
