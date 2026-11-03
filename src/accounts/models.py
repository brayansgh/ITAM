import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models

class Role(models.TextChoices):
    ADMINISTRATOR = 'ADMIN', 'Administrador'
    TECHNOLOGY = 'TECH', 'Tecnología'
    CONSULTATION = 'CONSULT', 'Consulta'

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CONSULTATION)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"
