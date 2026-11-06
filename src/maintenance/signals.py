from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.audit import current_actor
from inventory.models import Asset, AssetStatus
from .models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
from .services import open_repairs, synchronize_ticket_asset


@receiver(post_save, sender=Asset)
def sync_inventory_to_maintenance(sender, instance, using, update_fields=None, **kwargs):
    # Asset.save mantiene el bloqueo y la transacción durante estas señales.
    if update_fields is not None and "status" not in update_fields:
        return
    actor = current_actor(instance)
    if instance.status in (AssetStatus.IN_MAINTENANCE, AssetStatus.MAINTENANCE):
        needed = not open_repairs(instance, using).exists()
        ticket_type = MaintenanceType.CORRECTIVE
    elif instance.status == AssetStatus.DECOMMISSIONED:
        needed = not MaintenanceRecord.objects.using(using).filter(
            asset_id=instance.pk, type=MaintenanceType.DECOMMISSION,
        ).exclude(status=MaintenanceStatus.CANCELLED).exists()
        ticket_type = MaintenanceType.DECOMMISSION
    else:
        return
    if needed:
        users = get_user_model().objects.using(using)
        reporter = actor or users.filter(is_superuser=True).first() or users.first()
        if reporter is None:
            return
        ticket = MaintenanceRecord(
            asset_id=instance.pk, type=ticket_type, status=MaintenanceStatus.OPEN,
            description="Ticket autogenerado por cambio de estado del inventario.",
            reported_by=reporter,
        )
        ticket._history_user = actor
        ticket.save(using=using)


@receiver(post_save, sender=MaintenanceRecord)
@receiver(post_delete, sender=MaintenanceRecord)
def sync_maintenance_to_inventory(sender, instance, using, **kwargs):
    with transaction.atomic(using=using):
        synchronize_ticket_asset(instance.asset_id, current_actor(instance), using)
