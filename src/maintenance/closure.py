"""Validaciones de cierre compartidas por modelos, documentos y administradores."""
from django.core.exceptions import ValidationError
from .models import MaintenanceStatus, MaintenanceType

CLOSED_STATUSES = (MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED)


def validate_ticket(ticket, using, previous=None, asset=None):
    if previous and previous.status in CLOSED_STATUSES:
        raise ValidationError("El ticket está cerrado y solo permite consulta.")
    if previous and previous.asset_id != ticket.asset_id:
        raise ValidationError({"asset": "No se puede trasladar un ticket existente a otro activo."})
    if previous and previous.return_item_id and previous.return_item_id != ticket.return_item_id:
        raise ValidationError("No se puede sustituir ni retirar el acta vinculada al ticket.")
    if ticket.return_item_id:
        item = ticket.return_item
        if (
            ticket.type != MaintenanceType.DECOMMISSION
            or item.assignment.asset_id != ticket.asset_id
            or item.assignment.status != "RETURNED"
            or not item.offboarding_record.return_reason
        ):
            raise ValidationError("El acta de origen debe corresponder a una devolución registrada para este activo.")
    from inventory.models import Asset, AssetStatus
    asset = asset or Asset.objects.using(using).filter(pk=ticket.asset_id).first()
    if asset is None:
        return
    if previous is None and asset.status == AssetStatus.DECOMMISSIONED:
        raise ValidationError({"asset": "No se pueden abrir tickets sobre un activo dado de baja."})
    if ticket.type == MaintenanceType.DECOMMISSION and ticket.status == MaintenanceStatus.COMPLETED:
        errors = {}
        if not (ticket.resolution_notes or "").strip():
            errors["resolution_notes"] = "Documenta el motivo y resultado de la baja antes de completarla."
        if asset.assignments.using(using).filter(status="ACTIVE").exists():
            errors["status"] = "Registra la devolución de la custodia antes de completar la baja."
        from .models import MaintenanceRecord
        if MaintenanceRecord.objects.using(using).filter(asset_id=asset.pk, status__in=(MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS)).exclude(pk=ticket.pk).exists():
            errors["status"] = "Cierra o cancela los demás trabajos pendientes antes de completar la baja."
        if errors:
            raise ValidationError(errors)
