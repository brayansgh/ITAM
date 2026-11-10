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

    def get_display_name(self):
        return self.get_full_name() or self.get_username()

    def __str__(self):
        return self.get_display_name()
