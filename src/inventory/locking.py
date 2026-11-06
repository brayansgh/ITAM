from django.core.exceptions import ValidationError
from django.db import router, transaction


def save_asset_attachment(instance, save, *args, **kwargs):
    from .models import Asset, AssetStatus
    using = kwargs.get("using") or router.db_for_write(type(instance), instance=instance)
    with transaction.atomic(using=using):
        asset = Asset.objects.using(using).select_for_update().get(pk=instance.asset_id)
        previous = type(instance).objects.using(using).filter(pk=instance.pk).first()
        if previous and previous.asset_id != instance.asset_id:
            raise ValidationError("No se puede trasladar un anexo a otro activo.")
        if asset.status == AssetStatus.DECOMMISSIONED:
            raise ValidationError("Los anexos del activo dado de baja son de solo consulta.")
        return save(*args, **kwargs)
