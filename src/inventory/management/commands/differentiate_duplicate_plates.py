from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from inventory.models import Asset, AssetStatus


class Command(BaseCommand):
    help = 'Diferencia placas duplicadas con autorización. Solo conteos; sin datos personales.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        duplicates = list(Asset.objects.exclude(legacy_asset_tag__isnull=True).exclude(legacy_asset_tag='')
                          .values('legacy_asset_tag').annotate(n=Count('pk')).filter(n__gt=1))
        changed = 0
        for row in duplicates:
            assets = list(Asset.objects.select_for_update().filter(legacy_asset_tag=row['legacy_asset_tag']).order_by('created_at', 'pk'))
            frozen = [a for a in assets if a.status == AssetStatus.DECOMMISSIONED]
            if len(frozen) > 1:
                raise CommandError('Hay varias bajas con la misma placa. No se alteró ningún registro; requiere revisión excepcional.')
            keeper = frozen[0] if frozen else assets[0]
            for asset in assets:
                if asset.pk == keeper.pk:
                    continue
                number = 1
                while True:
                    candidate = f'{row["legacy_asset_tag"][:39]}-DUP-{number:04d}'
                    if not Asset.objects.filter(legacy_asset_tag=candidate).exists():
                        break
                    number += 1
                changed += 1
                if options['apply']:
                    asset.legacy_asset_tag = candidate
                    asset._change_reason = 'Placa duplicada diferenciada con autorización; código interno y propietaria conservados.'
                    asset.save(update_fields=['legacy_asset_tag', 'updated_at'])
        self.stdout.write(f'Grupos duplicados: {len(duplicates)}. Placas {"modificadas" if options["apply"] else "por modificar"}: {changed}.')
