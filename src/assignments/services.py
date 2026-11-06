from inventory.models import Asset, AssetStatus
from employees.models import Employee
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import AssetStatus

from .models import Assignment, AssignmentStatus


@transaction.atomic
def return_assignment(*, assignment_id, condition):
    """
    Registra la devolución de un activo asignado.

    Bloquea la asignación durante la operación para evitar
    devoluciones simultáneas.
    """

    # 1. Consultar y bloquear la asignación y su activo.
    try:
        assignment = (
            Assignment.objects
            .select_for_update()
            .select_related("asset")
            .get(pk=assignment_id)
        )
    except Assignment.DoesNotExist:
        raise ValidationError(
            "La asignación que intentas devolver no existe."
        )

    # 2. Comprobar que la asignación siga vigente.
    if assignment.status != AssignmentStatus.ACTIVE:
        raise ValidationError(
            "Esta asignación ya no está vigente o fue devuelta anteriormente."
        )

    # 3. Validar la condición de devolución.
    condition = (condition or "").strip()

    if not condition:
        raise ValidationError(
            "Debes registrar la condición del activo al devolverlo."
        )

    # 4. Registrar la devolución.
    assignment.status = AssignmentStatus.RETURNED
    assignment.returned_at = timezone.now()
    assignment.return_condition = condition

    assignment.save(
        update_fields=[
            "status",
            "returned_at",
            "return_condition",
            "updated_at",
        ]
    )

    # 5. Actualizar el estado del activo.
    asset = assignment.asset
    asset.status = AssetStatus.AVAILABLE

    asset.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return assignment
@transaction.atomic
def create_assignment(*, asset_id, employee_id, assigned_by, initial_condition):
    """
    Crea una asignación y actualiza el estado del activo.

    Bloquea el activo para evitar asignaciones simultáneas.
    """

    # 1. Validar la condición inicial.
    initial_condition = (initial_condition or "").strip()

    if not initial_condition:
        raise ValidationError(
            "Debes registrar la condición del activo al entregarlo."
        )

    # 2. Consultar y bloquear el activo.
    try:
        asset = Asset.objects.select_for_update().get(pk=asset_id)
    except Asset.DoesNotExist:
        raise ValidationError(
            "El activo que intentas asignar no existe."
        )

    # 3. Comprobar que esté disponible.
    if asset.status != AssetStatus.AVAILABLE:
        raise ValidationError(
            "El activo no está disponible para una nueva asignación."
        )

    # 4. Comprobar que exista el empleado.
    try:
        employee = Employee.objects.get(pk=employee_id)
    except Employee.DoesNotExist:
        raise ValidationError(
            "El empleado al que intentas asignar el activo no existe."
        )

    # 5. Crear la asignación.
    assignment = Assignment.objects.create(
        asset=asset,
        employee=employee,
        assigned_by=assigned_by,
        initial_condition=initial_condition,
        status=AssignmentStatus.ACTIVE,
    )

    # 6. Actualizar el estado del activo.
    asset.status = AssetStatus.ASSIGNED
    asset.save(update_fields=["status", "updated_at"])

    return assignment
