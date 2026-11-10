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
def sync_maintenance_to_inventory(sender, instance, using, signal, **kwargs):
    with transaction.atomic(using=using):
        # Una baja histórica no es una orden de dar de baja nuevamente el activo.
        synchronize_ticket_asset(instance.asset_id, current_actor(instance), using,
            completed_decommission=(signal is post_save and instance.type == MaintenanceType.DECOMMISSION
                                    and instance.status == MaintenanceStatus.COMPLETED))


from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from inventory.models import AssetSpecs, AssetNetwork, AssetWarranty, DecommissionedAsset
from .models import MaintenanceDocument
from .closure import CLOSED_STATUSES


def guard_frozen_record(sender, instance, using, **kwargs):
    with transaction.atomic(using=using):
        # La protección usa las relaciones persistidas, nunca FKs alteradas en memoria.
        stored = sender._base_manager.using(using).filter(pk=instance.pk).first()
        if stored is None:
            return
        instance = stored
        record = None
        if isinstance(instance, Asset):
            asset_id = instance.pk
        elif isinstance(instance, (AssetSpecs, AssetNetwork, AssetWarranty)):
            asset_id = instance.asset_id
        else:
            record = instance if isinstance(instance, MaintenanceRecord) else MaintenanceRecord.objects.using(using).get(pk=instance.maintenance_id)
            asset_id = record.asset_id
        asset = Asset.objects.using(using).select_for_update().filter(pk=asset_id).first()
        if asset is not None and asset.status == AssetStatus.DECOMMISSIONED:
            raise ValidationError("El activo dado de baja y sus anexos son de solo consulta.")
        if record is not None:
            record.refresh_from_db(using=using)
            if record.status in CLOSED_STATUSES:
                raise ValidationError("El ticket cerrado y sus documentos no se pueden eliminar.")


for model in (Asset, DecommissionedAsset, AssetSpecs, AssetNetwork, AssetWarranty, MaintenanceRecord, MaintenanceDocument):
    pre_delete.connect(guard_frozen_record, sender=model, dispatch_uid="freeze_delete_" + model._meta.label)
