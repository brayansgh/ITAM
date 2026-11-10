from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assignments.models import Assignment
from employees.models import Employee
from inventory.models import Asset, AssetStatus, Category, AssetGroup
from maintenance.models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
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

    def test_breadcrumbs_use_current_navigation_labels(self):
        import re
        from django.utils.html import strip_tags

        cases = [
            ('assignments_assignment_changelist', [], 'Inicio › Historial de asignaciones'),
            ('employees_employee_changelist', [], 'Inicio › Empleados'),
            ('assignments_employeeassetsummary_changelist', [], 'Inicio › Resumen por usuarios'),
            ('maintenance_maintenancerecord_changelist', [], 'Inicio › Mantenimiento'),
            ('maintenance_decommission_add', [], 'Inicio › Bajas › Iniciar trámite de baja'),
            ('inventory_asset_change', [self.asset.pk], f'Inicio › Inventario de activos › {self.asset}'),
            ('itam_documents', [], 'Inicio › Documentos y actas'),
        ]
        for route, args, expected in cases:
            with self.subTest(route=route):
                response = self.client.get(reverse('admin:' + route, args=args))
                html = response.content.decode()
                trail = re.search(r'<div class="breadcrumbs">(.*?)</div>', html, re.S)
                self.assertIsNotNone(trail)
                self.assertEqual(' '.join(strip_tags(trail[1]).split()), expected)
        self.assertNotContains(self.client.get(reverse('admin:index')), 'class="breadcrumbs"')
        app = self.client.get(reverse('admin:app_list', kwargs={'app_label': 'employees'}))
        self.assertContains(app, 'Personas')
        trail = re.search(r'<div class="breadcrumbs">(.*?)</div>', app.content.decode(), re.S)
        self.assertIsNotNone(trail)
        self.assertNotIn('Employees', trail[1])

    def test_employee_admin_displays_spanish_labels_and_save_message(self):
        listing = reverse('admin:employees_employee_changelist')
        response = self.client.get(listing)
        for label in ('Empleados', 'Añadir empleado', 'Nombre completo', 'Tipo de documento',
                      'Compañía', 'Ubicación física', 'Área', 'Estado', 'Fecha de registro'):
            self.assertContains(response, label)
        self.assertNotContains(response, 'Full name')

        response = self.client.post(reverse('admin:employees_employee_change', args=[self.employee.pk]), {
            'full_name': 'Empleado sintético editado', 'document_type': 'CC',
            'company': self.company.pk, 'status': 'ACTIVE', '_save': 'Guardar',
        }, follow=True)
        self.assertRedirects(response, listing)
        self.assertContains(response, 'El empleado')
        self.assertContains(response, 'se cambió correctamente')

    def test_forms_offer_only_the_standard_save_action(self):
        for model in ['inventory_category', 'inventory_brand', 'inventory_asset',
                      'employees_employee', 'organizations_company',
                      'organizations_site', 'accounts_user', 'auth_group',
                      'assignments_assignment', 'maintenance_maintenancerecord']:
            with self.subTest(model=model):
                response = self.client.get(reverse(f'admin:{model}_add'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="_save"')
                self.assertContains(response, 'itam-change-form')
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

    def test_audit_catalog_groups_only_permitted_modules(self):
        response = self.client.get(reverse('admin:itam_audit'))
        self.assertEqual(response.status_code, 200)
        groups = response.context['audit_groups']
        self.assertTrue(groups)
        self.assertEqual([link for group in groups for link in group['links']], response.context['links'])
        viewer = User.objects.create_user(username='audit_catalog_viewer', is_staff=True, role='OTHER')
        viewer.user_permissions.add(Permission.objects.get(codename='view_category'))
        self.client.force_login(viewer)
        response = self.client.get(reverse('admin:itam_audit'))
        self.assertContains(response, reverse('admin:inventory_category_changelist'))
        links = [link['url'] for group in response.context['audit_groups'] for link in group['links']]
        self.assertEqual(links, [reverse('admin:inventory_category_changelist')])
        viewer.user_permissions.clear()
        response = self.client.get(reverse('admin:itam_audit'))
        self.assertEqual(response.context['audit_groups'], [])
        self.assertContains(response, 'Sin módulos disponibles')

    def test_documents_identify_type_employee_and_keep_protected_links(self):
        from assignments.models import OffboardingRecord, ReturnReason
        from assignments.services import create_assignment
        from maintenance.models import MaintenanceDocument
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                       assigned_by=self.user, initial_condition='Buen estado')
        assignment.signed_act_pdf = 'actas/synthetic.pdf'
        assignment.save(update_fields=['signed_act_pdf'])
        returned = OffboardingRecord.objects.create(employee=self.employee, received_by=self.user,
                                                     return_reason=ReturnReason.DAMAGE, pdf='actas_desvinculacion/synthetic.pdf')
        retired = OffboardingRecord.objects.create(employee=self.employee, received_by=self.user,
                                                    pdf='actas_desvinculacion/synthetic-retired.pdf')
        ticket = MaintenanceRecord.objects.create(asset=self.asset, type=MaintenanceType.PREVENTIVE,
                                                  reported_by=self.user, description='Prueba documental')
        document = MaintenanceDocument.objects.create(maintenance=ticket, document='maintenance_docs/synthetic.pdf')
        for kind, label, employee, url in [
            ('entrega', 'Entrega', self.employee.full_name, reverse('download_act_pdf', args=[assignment.pk])),
            ('devolucion', 'Devolución', self.employee.full_name, reverse('admin:assignments_offboardingrecord_view_pdf', args=[returned.pk])),
            ('desvinculacion', 'Desvinculación', self.employee.full_name, reverse('admin:assignments_offboardingrecord_view_pdf', args=[retired.pk])),
            ('mantenimiento', 'Mantenimiento', 'No aplica', reverse('admin:maintenance_document_download', args=[document.pk])),
        ]:
            with self.subTest(kind=kind):
                response = self.client.get(reverse('admin:itam_documents'), {'tipo': kind})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['rows'][0]['document_type'], label)
                self.assertEqual(response.context['rows'][0]['employee'], employee)
                self.assertContains(response, '<th>Tipo de documento</th>')
                self.assertContains(response, '<th>Empleado</th>')
                self.assertContains(response, employee)
                self.assertContains(response, url)
                self.assertNotContains(response, '/media/')
        viewer = User.objects.create_user(username='document_denied', is_staff=True, role='OTHER')
        self.client.force_login(viewer)
        for kind in ['entrega', 'devolucion', 'mantenimiento']:
            self.assertEqual(self.client.get(reverse('admin:itam_documents'), {'tipo': kind}).status_code, 403)

    def test_closed_tickets_use_shared_style_without_mutating_controls(self):
        from core.testing import complete_decommission
        closed = complete_decommission(self.asset, self.user)
        url = reverse('admin:maintenance_maintenancerecord_change', args=[closed.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'itam-change-form')
        self.assertContains(response, 'Solo consulta')
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, 'class="deletelink"')
        self.assertNotContains(response, 'type="file"')
        self.assertEqual(self.client.post(url, {'status': 'OPEN'}).status_code, 403)
        frozen = self.client.get(reverse('admin:inventory_decommissionedasset_change', args=[self.asset.pk]), {'editar': 1})
        self.assertEqual(frozen.status_code, 200)
        self.assertContains(frozen, 'itam-change-form')
        self.assertNotContains(frozen, 'name="_save"')

    def test_brand_assets_count_and_links_follow_inventory_permissions(self):
        from core.testing import complete_decommission
        from inventory.models import Brand

        brand = Brand.objects.create(name='Marca sintética')
        self.asset.brand = brand
        self.asset.save(update_fields=['brand'])
        retired = Asset.objects.create(company=self.company, owner_company=self.company,
                                       category=self.category, brand=brand)
        complete_decommission(retired, self.user)
        unrelated = Asset.objects.create(company=self.company, owner_company=self.company,
                                         category=self.category)
        brands_url = reverse('admin:inventory_brand_changelist')
        active_url = reverse('admin:inventory_asset_changelist')
        retired_url = reverse('admin:inventory_decommissionedasset_changelist')
        params = {'brand__id__exact': str(brand.pk)}

        response = self.client.get(brands_url)
        self.assertEqual(response.context['title'], 'Marcas')
        self.assertContains(response, 'Añadir marca')
        self.assertContains(response, 'class="itam-table-action itam-brand-active_assets"')
        self.assertContains(response, 'class="itam-table-action itam-brand-decommissioned_assets"')
        self.assertContains(response, 'Ver vigentes (1)')
        self.assertContains(response, 'Ver bajas (1)')
        self.assertContains(response, '<strong>2</strong>')
        self.assertContains(response, f'{active_url}?brand__id__exact={brand.pk}')
        self.assertContains(response, f'{retired_url}?brand__id__exact={brand.pk}')
        self.assertEqual(list(self.client.get(active_url, params).context['cl'].result_list), [self.asset])
        self.assertEqual([row.pk for row in self.client.get(retired_url, params).context['cl'].result_list], [retired.pk])

        response = self.client.get(active_url, {**params, 'q': self.asset.asset_tag})
        self.assertEqual(list(response.context['cl'].result_list), [self.asset])
        self.assertContains(response, 'class="itam-list-search-controls"')
        self.assertContains(response, f'name="brand__id__exact" value="{brand.pk}"')
        self.assertEqual(list(self.client.get(active_url, {**params, 'q': unrelated.asset_tag}).context['cl'].result_list), [])

        viewer = User.objects.create_user(username='brand_viewer', is_staff=True, role='OTHER')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='inventory', codename='view_brand'))
        self.client.force_login(viewer)
        response = self.client.get(brands_url)
        self.assertContains(response, 'Sin permiso para consultar activos')
        self.assertNotContains(response, 'Ver vigentes')
        self.assertNotContains(response, 'Ver bajas')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='inventory', codename='view_asset'))
        response = self.client.get(brands_url)
        self.assertContains(response, 'Ver vigentes (1)')
        self.assertNotContains(response, 'Ver bajas')
        self.assertEqual(self.client.get(retired_url, params).status_code, 403)

    def test_search_finds_primary_plate_and_internal_code_and_employee(self):
        for term in ['PL-SYNTHETIC', 'ACE-0001', 'Persona sintética']:
            response = self.client.get(reverse('admin:itam_search'), {'q': term})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(any(group['rows'] for group in response.context['results']))
            self.assertContains(response, 'itam-search-result')
            self.assertContains(response, 'Ver empleado' if term == 'Persona sintética' else 'Ver activo')

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
        self.assertContains(edit, 'Información técnica')
        self.assertContains(edit, 'Red y telefonía')
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

    def test_definitive_decommissions_use_audited_transition_and_keep_unknown_dates(self):
        later = Asset.objects.create(company=self.company, owner_company=self.company, category=self.category)
        legacy = Asset.objects.create(company=self.company, owner_company=self.company, category=self.category)
        Asset.objects.filter(pk=legacy.pk).update(status=AssetStatus.DECOMMISSIONED)
        legacy.history.all().update(status=AssetStatus.DECOMMISSIONED)

        url = reverse('admin:itam_decommissions')
        opened_at = datetime(2026, 12, 1, 14, tzinfo=timezone.utc)
        with patch('django.utils.timezone.now', return_value=opened_at):
            tickets = [
                MaintenanceRecord.objects.create(
                    asset=asset, type=MaintenanceType.DECOMMISSION, reported_by=self.user,
                    description='Trámite sintético',
                )
                for asset in (self.asset, later)
            ]
        pending = self.client.get(url)
        self.assertEqual([row['date'] for row in pending.context['rows']], [opened_at, opened_at])
        self.assertContains(pending, 'Fecha de registro')

        first_date = opened_at.replace(hour=15)
        second_date = opened_at.replace(hour=16)
        for ticket, closed_at in zip(tickets, (first_date, second_date)):
            with patch('django.utils.timezone.now', return_value=closed_at):
                ticket.status = MaintenanceStatus.COMPLETED
                ticket.resolution_notes = 'Cierre sintético documentado'
                ticket.save(update_fields=['status', 'resolution_notes'])

        response = self.client.get(url, {'estado': 'definitivas'})
        self.assertContains(response, 'Fecha de baja')
        self.assertContains(response, 'Sin fecha registrada', count=1)
        self.assertEqual(
            [(row['asset'].pk, row['date']) for row in response.context['rows']],
            [(later.pk, second_date), (self.asset.pk, first_date), (legacy.pk, None)],
        )

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
