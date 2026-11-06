from inventory.models import Asset, AssetStatus
from employees.models import Employee
from employees.validation import validate_assignment_recipient
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import AssetStatus

from .models import Assignment, AssignmentStatus


@transaction.atomic
def return_assignment(*, assignment_id, condition, returned_by=None):
    """
    Registra la devolución de un activo asignado.

    Bloquea la asignación durante la operación para evitar
    devoluciones simultáneas.
    """

    # 1. Consultar y bloquear la asignación y su activo.
    try:
        asset_id = Assignment.objects.values_list("asset_id", flat=True).get(pk=assignment_id)
        locked_asset = Asset.objects.select_for_update().get(pk=asset_id)
        assignment = Assignment.objects.select_for_update().get(pk=assignment_id, asset_id=asset_id)
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

    if returned_by is not None:
        assignment._history_user = returned_by
    assignment.save(
        update_fields=[
            "status",
            "returned_at",
            "return_condition",
            "updated_at",
        ]
    )

    # 5. Actualizar el estado del activo.
    asset = locked_asset
    if returned_by is not None:
        asset._history_user = returned_by
    from maintenance.services import resolved_status
    asset.status = resolved_status(asset, asset._state.db)

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
        employee = Employee.objects.select_for_update().get(pk=employee_id)
    except Employee.DoesNotExist:
        raise ValidationError(
            "El empleado al que intentas asignar el activo no existe."
        )

    validate_assignment_recipient(employee)

    # 5. Crear la asignación.
    assignment = Assignment(
        asset=asset,
        employee=employee,
        assigned_by=assigned_by,
        initial_condition=initial_condition,
        status=AssignmentStatus.ACTIVE,
    )

    assignment._history_user = assigned_by
    assignment.save()

    # 6. Actualizar el estado del activo.
    asset.status = AssetStatus.ASSIGNED
    asset._history_user = assigned_by
    asset.save(update_fields=["status", "updated_at"])

    return assignment
