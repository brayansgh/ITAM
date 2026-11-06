"""Identificación estable; los códigos legados explícitos se conservan."""
import re

from django.core.exceptions import ValidationError
from django.db import router
from organizations.models import Company


def validate_identity(asset, previous=None, using=None):
    using = using or asset._state.db or router.db_for_write(type(asset), instance=asset)
    if previous is None:
        previous = type(asset)._meta.concrete_model.objects.using(using).filter(pk=asset.pk).first()
    if previous is not None:
        if asset.owner_company_id != previous.owner_company_id:
            raise ValidationError({'owner_company': 'La propietaria se fija al crear el activo y no puede cambiar.'})
        if asset.asset_tag != previous.asset_tag:
            raise ValidationError({'asset_tag': 'El código interno del activo no puede cambiar.'})
    elif not asset.asset_tag:
        if not asset.owner_company_id:
            raise ValidationError({'owner_company': 'Selecciona la propietaria para generar el código interno.'})
        if not Company.objects.using(using).filter(pk=asset.owner_company_id, code__in=('ACE', 'SOL')).exists():
            raise ValidationError({'owner_company': 'La propietaria debe ser Acepalma (ACE) o Solutrans (SOL).'})
    elif re.fullmatch(r'(ACE|SOL)-\d{4}', asset.asset_tag):
        prefix = asset.asset_tag.split('-')[0]
        if not Company.objects.using(using).filter(pk=asset.owner_company_id, code=prefix).exists():
            raise ValidationError({'owner_company': 'El prefijo del código debe corresponder a la propietaria.'})


def prepare_identity(asset, previous, using, fields=None):
    # Un guardado parcial valida únicamente los valores que se persistirán.
    from copy import copy
    candidate = copy(asset)
    if previous is not None and fields is not None:
        if not {'owner_company', 'owner_company_id'}.intersection(fields):
            candidate.owner_company_id = previous.owner_company_id
        if 'asset_tag' not in fields:
            candidate.asset_tag = previous.asset_tag
    validate_identity(candidate, previous, using)
    if previous is not None or asset.asset_tag:
        return
    # El bloqueo de la propietaria serializa los consecutivos entre procesos.
    owner = Company.objects.using(using).select_for_update().get(pk=asset.owner_company_id)
    prefix = owner.code
    pattern = re.compile(rf'^{re.escape(prefix)}-(\d{{4}})$')
    from .models import Asset
    # El historial impide reutilizar el número de un activo eliminado.
    tags = Asset.objects.using(using).filter(asset_tag__startswith=prefix + '-').values_list('asset_tag', flat=True)
    historical = Asset.history.using(using).filter(asset_tag__startswith=prefix + '-').values_list('asset_tag', flat=True).distinct()
    last = max((int(m.group(1)) for tag in list(tags) + list(historical) if (m := pattern.fullmatch(tag))), default=0)
    if last >= 9999:
        raise ValidationError('Se agotaron los cuatro dígitos de esta propietaria. No se creó el activo.')
    asset.asset_tag = f'{prefix}-{last + 1:04d}'
