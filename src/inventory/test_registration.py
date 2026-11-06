from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from assignments.services import create_assignment
from employees.models import Employee
from organizations.models import Company
from .forms import AssetRegistrationForm
from .models import Asset, AssetGroup, Category


class AssetRegistrationTests(TestCase):
    def setUp(self):
        self.owner = Company.objects.create(name='Acepalma', code='ACE')
        self.other = Company.objects.create(name='Solutrans', code='SOL')
        self.category = Category.objects.create(name='Portátil', group=AssetGroup.COMPUTING)
        self.user = User.objects.create_superuser(username='registration_operator', password='Test-4826!')
        self.client.force_login(self.user)

    def create(self, **kwargs):
        return Asset.objects.create(category=self.category, company=self.other, owner_company=self.owner, **kwargs)

    def test_codes_are_generated_from_owner_with_independent_four_digit_sequences(self):
        first = self.create()
        second = self.create()
        third = Asset.objects.create(category=self.category, company=self.owner, owner_company=self.other)
        self.assertEqual([first.asset_tag, second.asset_tag, third.asset_tag], ['ACE-0001', 'ACE-0002', 'SOL-0001'])

    def test_code_of_deleted_asset_is_not_reused(self):
        first = self.create()
        first.delete()
        self.assertEqual(self.create().asset_tag, 'ACE-0002')

    def test_limit_does_not_generate_five_digit_code(self):
        self.create(asset_tag='ACE-9999')
        with self.assertRaises(ValidationError):
            self.create()
        self.assertEqual(Asset.objects.count(), 1)

    def test_generation_requires_explicit_supported_owner(self):
        with self.assertRaises(ValidationError):
            Asset.objects.create(category=self.category, company=self.owner)
        company = Company.objects.create(name='Otro propietario', code='EXT')
        with self.assertRaises(ValidationError):
            Asset.objects.create(category=self.category, company=self.owner, owner_company=company)

    def test_owner_and_internal_code_are_immutable_but_manager_can_change(self):
        asset = self.create()
        asset.owner_company = self.other
        with self.assertRaises(ValidationError):
            asset.save()
        asset.refresh_from_db()
        asset.asset_tag = 'ACE-0020'
        with self.assertRaises(ValidationError):
            asset.save()
        asset.refresh_from_db()
        asset.company = self.owner
        asset.save()
        self.assertEqual(asset.owner_company, self.owner)
        self.assertEqual(asset.asset_tag, 'ACE-0001')

    def test_partial_updates_validate_persisted_identity(self):
        asset = self.create()
        asset.owner_company = self.other
        asset.asset_tag = 'bad-change'
        asset.observations = 'Metadatos'
        asset.save(update_fields=['observations'])
        asset.refresh_from_db()
        self.assertEqual(asset.asset_tag, 'ACE-0001')
        self.assertEqual(asset.owner_company, self.owner)

    def test_legacy_plate_is_optional_and_unique_when_present(self):
        self.create(legacy_asset_tag=None)
        self.create(legacy_asset_tag='')
        self.create(legacy_asset_tag=None)
        self.create(legacy_asset_tag='UNICA-01')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create(legacy_asset_tag='UNICA-01')

    def test_cross_company_custody_preserves_owner_and_code(self):
        asset = self.create()
        employee = Employee.objects.create(company=self.other, full_name='Custodio de otra compañía')
        create_assignment(asset_id=asset.pk, employee_id=employee.pk, assigned_by=self.user, initial_condition='Bueno')
        asset.refresh_from_db()
        self.assertEqual(asset.owner_company, self.owner)
        self.assertEqual(asset.asset_tag, 'ACE-0001')

    def test_form_rejects_category_from_another_group(self):
        form = AssetRegistrationForm(data={'group': AssetGroup.TELEPHONY, 'category': str(self.category.pk), 'owner_company': str(self.owner.pk), 'company': str(self.owner.pk), 'status': 'AVAILABLE', 'property_type': 'OWNED'})
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

    def test_legacy_category_can_be_edited_without_reclassification(self):
        legacy = Category.objects.create(name='Tipo heredado')
        asset = self.create()
        asset.category = legacy
        asset.save()
        response = self.client.get(reverse('admin:inventory_asset_change', args=[asset.pk]), {'editar': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['adminform'].form.fields['group'].initial, '')

    def test_catalog_is_idempotent_and_includes_radiotelephone_without_modifying_legacy(self):
        legacy = Category.objects.create(name='Monitor')
        call_command('initialize_asset_catalog', stdout=StringIO())
        count = Category.objects.count()
        call_command('initialize_asset_catalog', stdout=StringIO())
        self.assertEqual(Category.objects.count(), count)
        legacy.refresh_from_db()
        self.assertEqual(legacy.group, '')
        self.assertTrue(Category.objects.filter(name='Radioteléfono', group=AssetGroup.TELEPHONY).exists())
        self.assertEqual(Category.objects.get(name='Radioteléfono').history.count(), 1)

    def test_new_admin_registration_generates_code_and_audits_actor(self):
        data = {'group': AssetGroup.COMPUTING, 'category': str(self.category.pk), 'company': str(self.other.pk), 'owner_company': str(self.owner.pk), 'legacy_asset_tag': 'PL-NEW', 'property_type': 'OWNED', 'status': 'AVAILABLE', '_save': 'Guardar'}
        for prefix in ('specs', 'network', 'warranties'):
            data.update({prefix + '-TOTAL_FORMS': '0', prefix + '-INITIAL_FORMS': '0', prefix + '-MIN_NUM_FORMS': '0', prefix + '-MAX_NUM_FORMS': '1000'})
        response = self.client.post(reverse('admin:inventory_asset_add'), data)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        asset = Asset.objects.get(legacy_asset_tag='PL-NEW')
        self.assertEqual(asset.asset_tag, 'ACE-0001')
        self.assertEqual(asset.history.first().history_user, self.user)

    def test_forged_owner_and_code_in_edit_post_are_ignored(self):
        asset = self.create()
        data = {'group': AssetGroup.COMPUTING, 'category': str(self.category.pk), 'company': str(self.other.pk), 'owner_company': str(self.other.pk), 'asset_tag': 'SOL-9876', 'property_type': 'OWNED', 'status': 'AVAILABLE', '_save': 'Guardar'}
        for prefix in ('specs', 'network', 'warranties'):
            data.update({prefix + '-TOTAL_FORMS': '0', prefix + '-INITIAL_FORMS': '0', prefix + '-MIN_NUM_FORMS': '0', prefix + '-MAX_NUM_FORMS': '1000'})
        response = self.client.post(reverse('admin:inventory_asset_change', args=[asset.pk]), data)
        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.owner_company, self.owner)
        self.assertEqual(asset.asset_tag, 'ACE-0001')


class AssetCodeConcurrencyTests(TransactionTestCase):
    def test_parallel_registrations_have_distinct_consecutive_codes(self):
        owner = Company.objects.create(name='Acepalma', code='ACE')
        category = Category.objects.create(name='Portátil', group=AssetGroup.COMPUTING)
        def create_one(_):
            close_old_connections()
            try:
                return Asset.objects.create(company_id=owner.pk, owner_company_id=owner.pk, category_id=category.pk).asset_tag
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(create_one, range(4)))
        self.assertEqual(set(codes), {'ACE-0001', 'ACE-0002', 'ACE-0003', 'ACE-0004'})
