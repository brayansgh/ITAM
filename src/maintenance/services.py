"""Reglas de disponibilidad compartidas por inventario, tickets y devoluciones."""
from django.core.exceptions import ValidationError
from inventory.models import AssetStatus
from .models import MaintenanceRecord, MaintenanceStatus, MaintenanceType

OPEN_STATUSES = (MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS)
PRESERVED_STATUSES = (AssetStatus.DECOMMISSIONED, AssetStatus.RETIRED, AssetStatus.LOST, AssetStatus.IN_TRANSIT)


def open_repairs(asset, using):
    return MaintenanceRecord.objects.using(using).filter(
        asset_id=asset.pk, status__in=OPEN_STATUSES,
    ).exclude(type=MaintenanceType.DECOMMISSION)


def resolved_status(asset, using):
    if asset.status in PRESERVED_STATUSES:
        return asset.status
    if MaintenanceRecord.objects.using(using).filter(
        asset_id=asset.pk, type=MaintenanceType.DECOMMISSION,
    ).exclude(status=MaintenanceStatus.CANCELLED).exists():
        return AssetStatus.DECOMMISSIONED
    if open_repairs(asset, using).exists():
        return AssetStatus.IN_MAINTENANCE
    if asset.assignments.using(using).filter(status="ACTIVE").exists():
        return AssetStatus.ASSIGNED
    return AssetStatus.AVAILABLE


def validate_asset_status(asset, using):
    if not asset.pk:
        return
    active = asset.assignments.using(using).filter(status="ACTIVE").exists()
    if asset.status in (AssetStatus.AVAILABLE, AssetStatus.DECOMMISSIONED) and active:
        raise ValidationError({"status": "Registra primero la devolución de los activos en custodia."})
    if asset.status in (AssetStatus.AVAILABLE, AssetStatus.ASSIGNED) and open_repairs(asset, using).exists():
        raise ValidationError({"status": "El activo tiene mantenimientos abiertos; cierra sus tickets primero."})


def synchronize_ticket_asset(asset_id, actor, using):
    from inventory.models import Asset
    asset = Asset.objects.using(using).select_for_update().get(pk=asset_id)
    status = resolved_status(asset, using)
    if status != asset.status:
        asset.status = status
        asset._history_user = actor
        asset._change_reason = "Disponibilidad recalculada según tickets y custodia vigente"
        asset.save(using=using, update_fields=["status", "updated_at"])
