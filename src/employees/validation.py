from django.core.exceptions import ValidationError
from .models import EmployeeStatus


def validate_assignment_recipient(employee):
    if employee.status == EmployeeStatus.RETIRO:
        raise ValidationError("No se pueden entregar activos a un empleado retirado.")
