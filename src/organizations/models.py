from django.db import models
from core.models import BaseModel

class Status(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Activo'
    INACTIVE = 'INACTIVE', 'Inactivo'

class Company(BaseModel):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Código corto (ej. ACE, SOL)")
    tax_id = models.CharField(max_length=50, blank=True, null=True, help_text="NIT o documento fiscal")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name = "Compañía"
        verbose_name_plural = "Compañías"

    def __str__(self):
        return self.name

class Site(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name = "Sede"
        verbose_name_plural = "Sedes"
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_site_per_company')
        ]

    def __str__(self):
        return self.name

class Area(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='areas')
    name = models.CharField(max_length=150)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_area_per_company')
        ]

    def __str__(self):
        return self.name
