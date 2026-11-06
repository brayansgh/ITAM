from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assignments.models import Assignment
from employees.models import Employee
from inventory.models import Asset, Category, AssetGroup
from maintenance.models import MaintenanceRecord, MaintenanceType
from organizations.models import Company


class CorporateAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='interface_operator', password='Test-4826!')
        self.company = Company.objects.create(name='Acepalma', code='ACE')
        self.category = Category.objects.create(name='Portátil', group=AssetGroup.COMPUTING)
        self.asset = Asset.objects.create(company=self.company, owner_company=self.company, category=self.category, legacy_asset_tag='PL-SYNTHETIC')
        self.employee = Employee.objects.create(company=self.company, full_name='Persona sintética')
        self.client.force_login(self.user)

    def test_all_main_screens_render_with_corporate_shell(self):
        for route, args in [('admin:index', []), ('admin:inventory_asset_changelist', []), ('admin:inventory_asset_add', []), ('admin:inventory_asset_change', [self.asset.pk]), ('admin:employees_employee_change', [self.employee.pk]), ('admin:itam_search', []), ('admin:itam_documents', []), ('admin:itam_decommissions', []), ('admin:itam_audit', [])]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'img/palma.png')
                self.assertContains(response, 'itam/admin.css')

    def test_forms_offer_only_the_standard_save_action(self):
        for model in ['inventory_category', 'inventory_brand', 'inventory_asset',
                      'employees_employee', 'organizations_company',
                      'organizations_site', 'accounts_user', 'auth_group',
                      'assignments_assignment', 'maintenance_maintenancerecord']:
            with self.subTest(model=model):
                response = self.client.get(reverse(f'admin:{model}_add'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="_save"')
                for action in ['_addanother', '_continue', '_saveasnew']:
                    self.assertNotContains(response, f'name="{action}"')
        response = self.client.get(reverse('admin:inventory_category_change', args=[self.category.pk]))
        self.assertContains(response, 'name="_save"')
        self.assertContains(response, 'class="closelink itam-cancel"')
        self.assertContains(response, 'class="deletelink"')

    def test_read_only_form_does_not_gain_save_or_delete_buttons(self):
        viewer = User.objects.create_user(username='category_viewer', is_staff=True, role='OTHER')
        viewer.user_permissions.add(Permission.objects.get(codename='view_category'))
        self.client.force_login(viewer)
        response = self.client.get(reverse('admin:inventory_category_change', args=[self.category.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, 'class="deletelink"')
        self.assertContains(response, 'Volver al listado')

    def test_navigation_toggle_belongs_to_header_branding(self):
        response = self.client.get(reverse('admin:index'))
        html = response.content.decode()
        branding = html.split('<div id="branding">', 1)[1].split('</div>', 1)[0]
        self.assertIn('class="itam-menu-toggle"', branding)
        self.assertEqual(html.count('class="itam-menu-toggle"'), 1)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('admin:login')), 'class="itam-menu-toggle"')

    def test_admin_lists_have_no_bulk_actions_or_selection_checkboxes(self):
        from django.contrib import admin
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.user
        for model, model_admin in admin.site._registry.items():
            with self.subTest(model=model._meta.label):
                self.assertEqual(model_admin.get_actions(request), {})
        for model in ['inventory_category', 'inventory_asset', 'employees_employee',
                      'employees_retiredemployee', 'assignments_assignment',
                      'maintenance_maintenancerecord', 'data_imports_stagingasset',
                      'accounts_user', 'auth_group']:
            with self.subTest(listing=model):
                response = self.client.get(reverse(f'admin:{model}_changelist'))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'name="action"')
                self.assertNotContains(response, 'name="_selected_action"')
                self.assertNotContains(response, 'id="action-toggle"')
        self.client.post(reverse('admin:inventory_category_changelist'), {
            'action': 'delete_selected', '_selected_action': str(self.category.pk), 'post': 'yes',
        })
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_search_finds_primary_plate_and_internal_code_and_employee(self):
        for term in ['PL-SYNTHETIC', 'ACE-0001', 'Persona sintética']:
            response = self.client.get(reverse('admin:itam_search'), {'q': term})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(any(group['rows'] for group in response.context['results']))

    def test_global_search_does_not_leak_records_without_module_permission(self):
        user = User.objects.create_user(username='restricted', is_staff=True, role='OTHER')
        self.client.force_login(user)
        response = self.client.get(reverse('admin:itam_search'), {'q': 'PL-SYNTHETIC'})
        self.assertEqual(response.context['results'][0]['rows'], [])
        dashboard = self.client.get(reverse('admin:index'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['metrics'], [])

    def test_search_escapes_user_input(self):
        response = self.client.get(reverse('admin:itam_search'), {'q': '<script>synthetic()</script>'})
        self.assertNotContains(response, '<script>synthetic()</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_asset_detail_is_readable_and_edit_is_separate(self):
        route = reverse('admin:inventory_asset_change', args=[self.asset.pk])
        detail = self.client.get(route)
        self.assertTrue(detail.context['asset_detail'])
        self.assertContains(detail, 'Editar activo')
        html = detail.content.decode()
        tools = html.split('<ul class="object-tools">', 1)[1].split('</ul>', 1)[0]
        self.assertIn('Editar activo', tools)
        self.assertIn(reverse('admin:inventory_asset_history', args=[self.asset.pk]), tools)
        self.assertNotContains(detail, 'name="_save"')
        edit = self.client.get(route, {'editar': 1})
        self.assertFalse(edit.context['asset_detail'])
        self.assertContains(edit, 'name="_save"')
        self.assertNotIn('owner_company', edit.context['adminform'].form.fields)
        self.assertNotIn('asset_tag', edit.context['adminform'].form.fields)

    def test_category_options_require_auth_and_filter_by_group(self):
        url = reverse('admin:inventory_category_options')
        self.assertEqual(self.client.get(url, {'group': AssetGroup.COMPUTING}).json()['results'][0]['name'], 'Portátil')
        self.assertEqual(self.client.get(url, {'group': AssetGroup.TELEPHONY}).json()['results'], [])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_decommissions_and_maintenance_are_separate_without_bypassing_closure(self):
        ticket = MaintenanceRecord.objects.create(asset=self.asset, type=MaintenanceType.DECOMMISSION, reported_by=self.user, description='Trámite sintético')
        response = self.client.get(reverse('admin:maintenance_maintenancerecord_changelist'))
        self.assertNotIn(ticket, list(response.context['cl'].queryset))
        hub = self.client.get(reverse('admin:itam_decommissions'))
        self.assertEqual(len(hub.context['rows']), 1)
        add = self.client.get(reverse('admin:maintenance_maintenancerecord_add'), {'type': 'DECOMMISSION'})
        self.assertTrue(add.context['adminform'].form.fields['type'].disabled)
        ticket.status = 'CANCELLED'
        ticket.save()
        self.assertEqual(len(self.client.get(reverse('admin:itam_decommissions'), {'estado': 'cancelados'}).context['rows']), 1)
        self.assertEqual(self.client.post(reverse('admin:maintenance_maintenancerecord_change', args=[ticket.pk]), {'description': 'forged'}).status_code, 403)

    def test_read_only_user_cannot_access_new_mutating_routes(self):
        viewer = User.objects.create_user(username='viewer', is_staff=True, role='OTHER')
        viewer.user_permissions.add(Permission.objects.get(codename='view_asset'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse('admin:inventory_asset_add')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:itam_documents')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:itam_decommissions')).status_code, 403)

    def test_consultation_role_does_not_see_summary_generation_button(self):
        from assignments.models import EmployeeAssetSummary
        from django.contrib import admin
        from django.test import RequestFactory
        viewer = User.objects.create_user(username='consultation', role='CONSULT', is_staff=True)
        request = RequestFactory().get('/')
        request.user = viewer
        self.assertNotIn('generate_pdf_button', admin.site._registry[EmployeeAssetSummary].get_list_display(request))
