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
def create_assignment(*, asset_id, employee_id, assigned_by, initial_condition, observations=None):
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

    if asset.assignments.filter(status=AssignmentStatus.ACTIVE).exists():
        raise ValidationError("El activo ya tiene una asignación vigente.")

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
        observations=observations,
        status=AssignmentStatus.ACTIVE,
    )

    assignment._history_user = assigned_by
    assignment.save()

    # 6. Actualizar el estado del activo.
    asset.status = AssetStatus.ASSIGNED
    asset._history_user = assigned_by
    asset.save(update_fields=["status", "updated_at"])

    return assignment


class ReturnPdfError(Exception):
    """El acta no se pudo generar o almacenar."""


@transaction.atomic
def link_return_to_decommission(*, item, actor, authorize):
    from maintenance.models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
    from maintenance.services import OPEN_STATUSES

    assignment = item.assignment
    asset = Asset.objects.select_for_update().get(pk=assignment.asset_id)
    if not item.offboarding_record.return_reason or assignment.status != AssignmentStatus.RETURNED:
        raise ValidationError("Se necesita un acta de devolución de activos registrada.")
    if asset.assignments.filter(status=AssignmentStatus.ACTIVE).exists():
        raise ValidationError("El activo tiene una custodia vigente. Registra su devolución antes de vincular el acta.")
    if asset.status == AssetStatus.DECOMMISSIONED:
        raise ValidationError("Este activo ya está dado de baja.")
    tickets = list(MaintenanceRecord.objects.select_for_update().filter(
        asset=asset, type=MaintenanceType.DECOMMISSION, status__in=OPEN_STATUSES,
    )[:2])
    if len(tickets) > 1:
        raise ValidationError("Hay varios trámites de baja abiertos para este activo. Revísalos antes de vincular el acta.")
    ticket = tickets[0] if tickets else None
    authorize(ticket)
    if ticket:
        if ticket.return_item_id == item.pk:
            return ticket
        if ticket.return_item_id:
            raise ValidationError("El trámite abierto ya está vinculado a otra devolución.")
        ticket.return_item = item
        ticket._history_user = actor
        ticket.save(update_fields=["return_item", "updated_at"])
        return ticket

    ticket = MaintenanceRecord(
        asset=asset, type=MaintenanceType.DECOMMISSION, status=MaintenanceStatus.OPEN,
        reported_by=actor, return_item=item,
        description=f"Motivo de devolución: {item.offboarding_record.get_return_reason_display()}.\n"
                    f"Condición al recibir: {item.condition}",
    )
    ticket._history_user = actor
    ticket.save()
    return ticket


def register_active_returns(*, employee, assignments, reason, condition, observations, actor,
                            authorize_decommission=None):
    from employees.models import EmployeeStatus
    from inventory.offboarding_pdf import generate_and_save_offboarding_pdf
    from .models import OffboardingRecord, OffboardingRecordItem, ReturnReason

    if reason not in ReturnReason.values:
        raise ValidationError("Selecciona un motivo de devolución válido.")
    selected = sorted(assignments, key=lambda assignment: assignment.asset_id)
    if not selected or any(assignment.employee_id != employee.pk for assignment in selected):
        raise ValidationError("Selecciona los activos vigentes de este empleado.")
    record = None
    try:
        with transaction.atomic():
            # Compartir el orden de bloqueo de los otros flujos de custodia.
            asset_ids = [assignment.asset_id for assignment in selected]
            list(Asset.objects.select_for_update().filter(pk__in=asset_ids).order_by("pk"))
            locked_employee = Employee.objects.select_for_update().get(pk=employee.pk)
            if locked_employee.status != EmployeeStatus.ACTIVE:
                raise ValidationError("Este flujo requiere un empleado activo.")
            record = OffboardingRecord(employee=locked_employee, received_by=actor,
                                       return_reason=reason, observations=observations)
            record._history_user = actor
            record.save()
            tickets = []
            for assignment in selected:
                returned = return_assignment(
                    assignment_id=assignment.pk, condition=condition, returned_by=actor,
                )
                if returned.employee_id != locked_employee.pk:
                    raise ValidationError("La custodia cambió. Actualiza la página.")
                item = OffboardingRecordItem(offboarding_record=record, assignment=returned,
                                            condition=returned.return_condition)
                item._history_user = actor
                item.save()
                if authorize_decommission is not None:
                    tickets.append(link_return_to_decommission(
                        item=item, actor=actor, authorize=authorize_decommission,
                    ))
            try:
                generate_and_save_offboarding_pdf(record)
            except Exception as error:
                raise ReturnPdfError from error
        return record, tickets
    except Exception:
        discard_return_pdf(record)
        raise


def discard_return_pdf(record):
    import logging

    if record and record.pdf:
        try:
            record.pdf.storage.delete(record.pdf.name)
        except Exception:
            logging.getLogger(__name__).warning("No se pudo retirar el PDF de una devolución revertida.")
