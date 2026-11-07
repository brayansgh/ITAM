from django.db import migrations


def preserve_existing_brands(apps, schema_editor):
    """Copia la asociación existente, sin reclasificar ni modificar historia anterior."""
    from django.utils import timezone
    Asset = apps.get_model('inventory', 'Asset')
    HistoricalAsset = apps.get_model('inventory', 'HistoricalAsset')
    using = schema_editor.connection.alias
    records = Asset.objects.using(using).filter(brand__isnull=True, model__brand__isnull=False).select_related('model')
    for asset in records.iterator():
        asset.brand_id = asset.model.brand_id
        Asset.objects.using(using).filter(pk=asset.pk).update(brand_id=asset.brand_id)
        values = {field.attname: getattr(asset, field.attname) for field in Asset._meta.concrete_fields}
        HistoricalAsset.objects.using(using).create(
            **values, history_type='~', history_date=timezone.now(), history_user_id=None,
            history_change_reason='Separación de marca: copia exacta de la asociación del modelo legado.',
        )


class Migration(migrations.Migration):
    dependencies = [('inventory', '0010_marca_modelo_independientes')]
    operations = [migrations.RunPython(preserve_existing_brands, migrations.RunPython.noop)]
