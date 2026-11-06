from io import StringIO
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from inventory.models import Asset


class DuplicatePlateTransitionTests(TransactionTestCase):
    def test_authorized_cleanup_preserves_frozen_asset_and_audits_only_actual_changes(self):
        executor = MigrationExecutor(connection)
        old_target = [('inventory', '0007_estandarizar_auditoria')]
        new_target = [('inventory', '0009_etiquetas_en_espanol')]
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            Company = apps.get_model('organizations', 'Company')
            Category = apps.get_model('inventory', 'Category')
            OldAsset = apps.get_model('inventory', 'Asset')
            company = Company.objects.create(name='Placas sintéticas', code='ACE')
            category = Category.objects.create(name='Tipo legado')
            frozen = OldAsset.objects.create(company=company, category=category, asset_tag='OLD-1', legacy_asset_tag='PL-DUP', status='DECOMMISSIONED')
            editable = OldAsset.objects.create(company=company, category=category, asset_tag='OLD-2', legacy_asset_tag='PL-DUP', status='ASSIGNED')
            stream = StringIO()
            call_command('differentiate_duplicate_plates', stdout=stream)
            self.assertEqual(Asset.objects.get(pk=editable.pk).legacy_asset_tag, 'PL-DUP')
            call_command('differentiate_duplicate_plates', apply=True, stdout=StringIO())
            updated = Asset.objects.get(pk=editable.pk)
            self.assertEqual(updated.legacy_asset_tag, 'PL-DUP-DUP-0001')
            self.assertEqual(updated.asset_tag, 'OLD-2')
            self.assertEqual(updated.status, 'ASSIGNED')
            self.assertEqual(updated.history.count(), 1)
            self.assertIsNone(updated.history.first().history_user)
            self.assertIn('autorización', updated.history.first().history_change_reason)
            self.assertEqual(Asset.objects.get(pk=frozen.pk).legacy_asset_tag, 'PL-DUP')
            call_command('differentiate_duplicate_plates', apply=True, stdout=StringIO())
            self.assertEqual(updated.history.count(), 1)
        finally:
            OldAsset.objects.filter(legacy_asset_tag='PL-DUP').exclude(pk=frozen.pk).update(legacy_asset_tag=None)
            MigrationExecutor(connection).migrate(new_target)
