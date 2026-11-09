from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import Role, User
from accounts.test_access_profiles import support_operator
from assignments import utils as assignment_pdf
from assignments.models import Assignment, AssignmentStatus
from assignments.services import create_assignment
from data_imports.models import ImportStatus, StagingAsset
from employees.models import Employee, EmployeeStatus
from organizations.models import Company
from .forms import AssetRegistrationForm
from .models import Asset, AssetGroup, AssetStatus, Brand, Category, ModelAsset


class AssetRegistrationTests(TestCase):
    def setUp(self):
        self.owner = Company.objects.create(name='Acepalma', code='ACE')
        self.other = Company.objects.create(name='Solutrans', code='SOL')
        self.category = Category.objects.create(name='Portátil', group=AssetGroup.COMPUTING)
        self.user = User.objects.create_superuser(username='registration_operator', password='Test-4826!', role=Role.ADMINISTRATOR)
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

    def test_model_edit_title_is_in_spanish(self):
        model = ModelAsset.objects.create(name='Modelo sintético')
        response = self.client.get(reverse('admin:inventory_modelasset_change', args=[model.pk]))
        self.assertEqual(response.context['title'], 'Modificar modelo')
        self.assertContains(response, 'Nombre')

    def test_add_form_renders_brand_catalog_and_popup_link_for_support(self):
        brand = Brand.objects.create(name='Marca A')
        expected = ModelAsset.objects.create(name='Modelo A', brand=brand)
        ModelAsset.objects.create(name='Modelo sin marca')
        self.client.force_login(support_operator(self.user))

        add_page = self.client.get(reverse('admin:inventory_asset_add'))
        self.assertEqual(list(add_page.context['adminform'].form.fields['model'].queryset), [])
        self.assertEqual(add_page.context['asset_model_catalog'], [
            {'id': expected.pk, 'name': expected.name, 'brand_id': brand.pk},
        ])
        self.assertContains(add_page, 'id="itam-model-catalog"')
        self.assertContains(add_page, 'id="add_id_model"')
        self.assertContains(add_page, 'asset-form.js?v=')

    def test_support_can_add_a_model_only_in_a_brand_popup(self):
        brand = Brand.objects.create(name='Marca A')
        other = Brand.objects.create(name='Marca B')
        support = support_operator(self.user)
        self.client.force_login(support)
        url = reverse('admin:inventory_modelasset_add')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {'_popup': 1, 'brand': 'inválida'}).status_code, 403)

        popup = f'{url}?_popup=1&brand={brand.pk}'
        form = self.client.get(popup).context['adminform'].form
        self.assertTrue(form.fields['brand'].disabled)
        self.assertEqual(str(form['brand'].value()), str(brand.pk))
        response = self.client.post(popup, {'name': 'Modelo nuevo', 'brand': other.pk, '_popup': '1'})
        self.assertTemplateUsed(response, 'admin/popup_response.html')
        model = ModelAsset.objects.get(name='Modelo nuevo')
        self.assertEqual(model.brand_id, brand.pk)
        self.assertEqual(model.history.first().history_user, support)

        viewer = User.objects.create_user(username='catalog_viewer', is_staff=True)
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(popup, {'name': 'Sin permiso'}).status_code, 403)
        self.assertFalse(ModelAsset.objects.filter(name='Sin permiso').exists())

    def test_new_form_rejects_a_model_from_another_brand(self):
        brand = Brand.objects.create(name='Marca A')
        model = ModelAsset.objects.create(name='Modelo B', brand=Brand.objects.create(name='Marca B'))
        form = AssetRegistrationForm(data={'brand': brand.pk, 'model': model.pk})
        self.assertIn('model', form.errors)

    def test_existing_asset_form_keeps_a_legacy_model_available(self):
        model = ModelAsset.objects.create(name='Modelo heredado')
        asset = self.create(brand=Brand.objects.create(name='Marca A'), model=model)
        form = AssetRegistrationForm(instance=asset)
        self.assertIn(model, form.fields['model'].queryset)
        self.assertEqual(form['model'].value(), model.pk)

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
        self.user = support_operator(self.user)
        self.client.force_login(self.user)
        data = {'group': AssetGroup.COMPUTING, 'category': str(self.category.pk), 'company': str(self.other.pk), 'owner_company': str(self.owner.pk), 'legacy_asset_tag': 'PL-NEW', 'property_type': 'OWNED', 'status': 'AVAILABLE', '_save': 'Guardar'}
        brand = Brand.objects.create(name='Marca A')
        model = ModelAsset.objects.create(name='Modelo A', brand=brand)
        data.update(brand=str(brand.pk), model=str(model.pk))
        for prefix in ('specs', 'network', 'warranties'):
            data.update({prefix + '-TOTAL_FORMS': '0', prefix + '-INITIAL_FORMS': '0', prefix + '-MIN_NUM_FORMS': '0', prefix + '-MAX_NUM_FORMS': '1000'})
        response = self.client.post(reverse('admin:inventory_asset_add'), data)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        asset = Asset.objects.get(legacy_asset_tag='PL-NEW')
        self.assertEqual(asset.asset_tag, 'ACE-0001')
        self.assertEqual((asset.brand_id, asset.model_id), (brand.pk, model.pk))
        self.assertEqual(asset.history.first().history_user, self.user)

    def assignment_registration_data(self, **overrides):
        data = {
            'group': AssetGroup.COMPUTING, 'category': self.category.pk, 'company': self.other.pk,
            'owner_company': self.owner.pk, 'property_type': 'OWNED', 'status': AssetStatus.ASSIGNED,
            '_save': 'Guardar', **overrides,
        }
        for prefix in ('specs', 'network', 'warranties'):
            data.update({f'{prefix}-TOTAL_FORMS': '0', f'{prefix}-INITIAL_FORMS': '0'})
        return data

    def test_support_creates_asset_and_active_assignment_in_one_submit(self):
        support = support_operator(self.user)
        self.client.force_login(support)
        employee = Employee.objects.create(company=self.other, full_name='Persona de prueba')
        url = reverse('admin:inventory_asset_add')
        page = self.client.get(url)
        self.assertContains(page, 'Asignar a una persona')
        self.assertContains(page, 'itam-registration-assignment')
        response = self.client.post(url, self.assignment_registration_data(
            assignment_employee=employee.pk, assignment_condition='Equipo operativo',
            assignment_observations='Se entrega con cargador',
        ))
        self.assertEqual(response.status_code, 302)
        assignment = Assignment.objects.get()
        self.assertEqual(assignment.status, AssignmentStatus.ACTIVE)
        self.assertEqual(assignment.employee, employee)
        self.assertEqual(assignment.assigned_by, support)
        self.assertEqual(assignment.initial_condition, 'Equipo operativo')
        self.assertEqual(assignment.observations, 'Se entrega con cargador')
        self.assertEqual(assignment.asset.status, AssetStatus.ASSIGNED)
        self.assertEqual(assignment.history.first().history_user, support)
        confirmation = reverse('admin:assignments_assignment_act', args=[assignment.pk])
        self.assertRedirects(response, confirmation + "?confirmada=1")
        self.assertContains(self.client.get(confirmation + '?confirmada=1'), 'data-open-on-load')
        self.assertFalse(assignment.signed_act_pdf)

    def test_assignment_registration_requires_condition_and_eligible_employee(self):
        retired = Employee.objects.create(company=self.other, full_name='Persona retirada', status=EmployeeStatus.RETIRO)
        response = self.client.post(reverse('admin:inventory_asset_add'), self.assignment_registration_data(
            assignment_employee=retired.pk, assignment_condition=' ',
        ))
        form = response.context['adminform'].form
        self.assertIn('assignment_employee', form.errors)
        self.assertIn('assignment_condition', form.errors)
        self.assertFalse(Asset.objects.exists())

    def test_asset_add_permission_alone_does_not_allow_assignment(self):
        operator = User.objects.create_user(username='asset_only', is_staff=True, role=Role.CONSULTATION)
        operator.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='inventory', codename__in=('add_asset', 'view_asset'),
        ))
        self.client.force_login(operator)
        url = reverse('admin:inventory_asset_add')
        self.assertNotContains(self.client.get(url), 'Asignar a una persona')
        response = self.client.post(url, self.assignment_registration_data())
        self.assertIn('status', response.context['adminform'].form.errors)
        self.assertFalse(Asset.objects.exists())

    def test_failed_assignment_rolls_back_asset_registration(self):
        employee = Employee.objects.create(company=self.other, full_name='Persona de prueba')
        data = self.assignment_registration_data(assignment_employee=employee.pk, assignment_condition='Operativo')
        with patch('assignments.services.create_assignment', side_effect=ValidationError('Conflicto de custodia')):
            response = self.client.post(reverse('admin:inventory_asset_add'), data)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(Asset.history.exists())
        self.assertFalse(Assignment.objects.exists())

    def test_edit_available_asset_requires_custodian_and_creates_assignment(self):
        support = support_operator(self.user)
        self.client.force_login(support)
        asset = self.create()
        employee = Employee.objects.create(company=self.other, full_name='Persona de prueba')
        url = reverse('admin:inventory_asset_change', args=[asset.pk]) + '?editar=1'
        self.assertContains(self.client.get(url), 'Asignar a una persona')
        response = self.client.post(url, self.assignment_registration_data())
        form = response.context['adminform'].form
        self.assertIn('assignment_employee', form.errors)
        self.assertIn('assignment_condition', form.errors)
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.AVAILABLE)
        self.assertFalse(Assignment.objects.exists())

        response = self.client.post(url, self.assignment_registration_data(
            assignment_employee=employee.pk, assignment_condition='Operativo', observations='Editado',
        ))
        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.ASSIGNED)
        self.assertEqual(asset.observations, 'Editado')
        assignment = asset.assignments.get(status=AssignmentStatus.ACTIVE)
        self.assertEqual(assignment.employee, employee)
        self.assertRedirects(response, reverse('admin:assignments_assignment_act', args=[assignment.pk]) + '?confirmada=1')

    def test_available_asset_offers_assignment_shortcut_and_pdf_confirmation(self):
        asset = self.create()
        employee = Employee.objects.create(company=self.other, full_name='Persona de prueba')
        detail = reverse('admin:inventory_asset_change', args=[asset.pk])
        add = reverse('admin:assignments_assignment_add')
        shortcut = self.client.get(detail).context['asset_assignment_url']
        self.assertEqual(shortcut, f'{add}?asset={asset.pk}')
        self.assertContains(self.client.get(detail), 'Asignar activo')
        form = self.client.get(shortcut).context['adminform'].form
        self.assertEqual(str(form['asset'].value()), str(asset.pk))
        self.assertContains(self.client.get(shortcut), 'Observaciones / Pérdida / Daños')
        observations = 'Incluye cargador & cable.\nLeve rayón en la carcasa.'
        response = self.client.post(shortcut, {
            'asset': asset.pk, 'employee': employee.pk, 'initial_condition': 'Operativo',
            'observations': observations, '_save': 'Guardar',
        })
        assignment = asset.assignments.get()
        self.assertEqual(assignment.observations, observations)
        self.assertEqual(assignment.history.first().observations, observations)
        confirmation = reverse('admin:assignments_assignment_act', args=[assignment.pk])
        self.assertRedirects(response, confirmation + "?confirmada=1")
        self.assertContains(self.client.get(confirmation + '?confirmada=1'), 'data-open-on-load')
        with patch.object(assignment_pdf, 'render_to_string', wraps=assignment_pdf.render_to_string) as rendered:
            response = self.client.post(confirmation, {'mode': 'delivery'})
        self.assertRedirects(response, confirmation)
        assignment.refresh_from_db()
        self.assertTrue(assignment.signed_act_pdf)
        html = assignment_pdf.render_to_string(*rendered.call_args.args)
        self.assertIn('Incluye cargador &amp; cable.<br>Leve rayón en la carcasa.', html)
        self.assertNotIn('ENTREGA DE ELEMENTOS TECNOLÓGICOS', html)
        self.assertNotContains(self.client.get(detail), '>Asignar activo</a>')

    def test_edit_permission_alone_does_not_allow_setting_assigned(self):
        asset = self.create()
        operator = User.objects.create_user(username='asset_editor', is_staff=True, role=Role.CONSULTATION)
        operator.user_permissions.add(Permission.objects.get(
            content_type__app_label='inventory', codename='change_asset',
        ))
        self.client.force_login(operator)
        url = reverse('admin:inventory_asset_change', args=[asset.pk]) + '?editar=1'
        page = self.client.get(url)
        self.assertNotContains(page, 'Asignar a una persona')
        response = self.client.post(url, self.assignment_registration_data())
        self.assertIn('status', response.context['adminform'].form.errors)
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.AVAILABLE)

    def test_direct_save_cannot_introduce_assigned_without_custody(self):
        with self.assertRaisesMessage(ValidationError, 'Registra una asignación vigente'):
            self.create(status=AssetStatus.ASSIGNED)
        with self.assertRaisesMessage(ValidationError, 'Registra una asignación vigente'):
            self.create(id=None, status=AssetStatus.ASSIGNED)
        asset = self.create()
        asset.status = AssetStatus.ASSIGNED
        with self.assertRaises(ValidationError):
            asset.save(update_fields=['status'])
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.AVAILABLE)

    def test_legacy_assigned_without_custody_can_edit_metadata(self):
        asset = self.create()
        Asset.objects.filter(pk=asset.pk).update(status=AssetStatus.ASSIGNED)
        asset.refresh_from_db()
        asset.observations = 'Metadato actualizado'
        asset.save()
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.ASSIGNED)
        self.assertEqual(asset.observations, 'Metadato actualizado')
        self.assertFalse(asset.assignments.exists())

    def test_import_without_delivery_condition_keeps_custody_row_pending(self):
        common = {'sheet_name': 'Prueba', 'company': self.other.name,
                  'element': self.category.name, 'status': ImportStatus.APPROVED}
        custody = StagingAsset.objects.create(
            **common, row_number=1, legacy_asset_tag='IMP-01', employee_name='Persona de prueba',
        )
        stock = StagingAsset.objects.create(**common, row_number=2, legacy_asset_tag='IMP-02')
        output = StringIO()
        call_command('process_approved', owner_code='ACE', stdout=output)
        custody.refresh_from_db()
        stock.refresh_from_db()
        self.assertIn('no tiene condición de entrega', output.getvalue())
        self.assertEqual(custody.status, ImportStatus.APPROVED)
        self.assertEqual(stock.status, ImportStatus.IMPORTED)
        self.assertEqual(Asset.objects.get().status, AssetStatus.AVAILABLE)

    def test_employee_profile_opens_assignment_with_employee_preselected(self):
        support = support_operator(self.user)
        self.client.force_login(support)
        employee = Employee.objects.create(company=self.other, full_name='Persona de prueba')
        asset = self.create()
        unavailable = self.create(status=AssetStatus.LOST)
        profile_url = reverse('admin:employees_employee_change', args=[employee.pk])
        assignment_url = reverse('admin:assignments_assignment_add')
        profile = self.client.get(profile_url)
        self.assertContains(profile, 'Asignar activo')
        form_url = profile.context['employee_assignment_url']
        page = self.client.get(form_url)
        self.assertEqual(str(page.context['adminform'].form['employee'].value()), str(employee.pk))
        autocomplete = self.client.get(reverse('admin:autocomplete'), {
            'app_label': 'assignments', 'model_name': 'assignment', 'field_name': 'asset',
        }).json()
        results = {item['id'] for item in autocomplete['results']}
        self.assertIn(str(asset.pk), results)
        self.assertNotIn(str(unavailable.pk), results)
        response = self.client.post(assignment_url, {
            'asset': asset.pk, 'employee': employee.pk, 'initial_condition': 'Operativo', '_save': 'Guardar',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Assignment.objects.get(asset=asset).employee, employee)

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
