from django.contrib import admin
from django.test import RequestFactory, TestCase

from accounts.models import User
from assignments.models import Assignment, AssignmentStatus
from employees.models import Employee
from organizations.models import Company
from .models import Asset, AssetStatus, Category


class AssetListTests(TestCase):
    def setUp(self):
        self.model_admin = admin.site._registry[Asset]
        self.request = RequestFactory().get("/admin/inventory/asset/")
        company = Company.objects.create(name="Empresa de prueba", code="INV")
        category = Category.objects.create(name="Portátiles de prueba")
        self.asset = Asset.objects.create(
            asset_tag="ACT-TEST", legacy_asset_tag="LEG-TEST",
            company=company, category=category,
        )
        self.employee = Employee.objects.create(full_name="Persona actual", company=company)
        self.user = User.objects.create_user(username="inventory_test")

    def assign(self, employee, status):
        return Assignment.objects.create(
            asset=self.asset, employee=employee, assigned_by=self.user,
            status=status, initial_condition="Buen estado",
        )

    def test_list_uses_legacy_tag_and_employee(self):
        columns = self.model_admin.get_list_display(self.request)
        self.assertEqual(columns[:2], ('asset_identity', 'classification'))
        self.assertIn('assigned_employee', columns)
        self.assertIn('LEG-TEST', str(self.model_admin.asset_identity(self.asset)))
        self.assertNotIn('asset_tag', columns)
        self.assertNotIn('category', columns)

    def test_only_active_assignment_is_shown_without_extra_queries(self):
        self.assign(self.employee, AssignmentStatus.ACTIVE)
        former_employee = Employee.objects.create(
            full_name="Persona anterior", company=self.asset.company,
        )
        self.assign(former_employee, AssignmentStatus.RETURNED)
        with self.assertNumQueries(1):
            asset = self.model_admin.get_queryset(self.request).get(pk=self.asset.pk)
            self.assertEqual(self.model_admin.assigned_employee(asset), "Persona actual")

    def test_returned_assignment_is_not_shown(self):
        self.assign(self.employee, AssignmentStatus.RETURNED)
        asset = self.model_admin.get_queryset(self.request).get(pk=self.asset.pk)
        self.assertEqual(self.model_admin.assigned_employee(asset), "Sin asignación")

    def test_unassigned_asset_is_shown_without_legacy_tag(self):
        self.asset.legacy_asset_tag = None
        self.asset.save()
        asset = self.model_admin.get_queryset(self.request).get(pk=self.asset.pk)
        self.assertIsNone(asset.legacy_asset_tag)
        self.assertEqual(self.model_admin.assigned_employee(asset), "Sin asignación")

    def test_decommissioned_assets_remain_excluded(self):
        from core.testing import complete_decommission
        complete_decommission(self.asset)
        self.assertFalse(self.model_admin.get_queryset(self.request).filter(pk=self.asset.pk).exists())


class LifecycleEscapingTests(TestCase):
    def test_lifecycle_escapes_all_user_controlled_fields(self):
        from accounts.models import User
        from assignments.models import Assignment
        from employees.models import Employee
        from inventory.models import DecommissionedAsset
        from maintenance.models import MaintenanceRecord, MaintenanceType
        company = Company.objects.create(name="Empresa", code="HTML")
        category = Category.objects.create(name="Categoría")
        asset = Asset.objects.create(asset_tag="HTML-001", category=category, company=company)
        user = User.objects.create_user(username="<b>operator</b>")
        employee = Employee.objects.create(company=company, full_name="<script>synthetic()</script>")
        Assignment.objects.create(asset=asset, employee=employee, assigned_by=user,
                                  initial_condition="Prueba", status="RETURNED")
        MaintenanceRecord.objects.create(asset=asset, reported_by=user, type=MaintenanceType.CORRECTIVE,
                                         description='<img src=x onerror="synthetic()">')
        model_admin = admin.site._registry[DecommissionedAsset]
        html = str(model_admin.ciclo_de_vida(asset))
        self.assertNotIn("<script>", html)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn("<b>operator</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&lt;b&gt;operator&lt;/b&gt;", html)
        self.assertIn("Devuelto", html)
        self.assertNotIn("Cerrado permanentemente por Baja", html)

    def test_empty_lifecycle_is_readable(self):
        from inventory.models import DecommissionedAsset
        company = Company.objects.create(name="Empresa", code="EMPTY")
        category = Category.objects.create(name="Categoría")
        asset = Asset.objects.create(asset_tag="EMPTY-001", category=category, company=company)
        html = str(admin.site._registry[DecommissionedAsset].ciclo_de_vida(asset))
        self.assertIn("Sin mantenimientos registrados.", html)
        self.assertIn("Sin asignaciones previas.", html)


class AssetCardTests(TestCase):
    def setUp(self):
        from organizations.models import Company
        self.user = User.objects.create_superuser(username="card_operator", password="Test-4826!")
        self.company = Company.objects.create(name="Empresa", code="CARD")
        self.category = Category.objects.create(name="Equipo")
        self.asset = Asset.objects.create(asset_tag="CARD-001", company=self.company, category=self.category)
        self.employee = Employee.objects.create(company=self.company, full_name="Persona vigente")
        self.client.force_login(self.user)

    def url(self, asset=None):
        from django.urls import reverse
        target = asset or self.asset
        model = "decommissionedasset" if target.status == AssetStatus.DECOMMISSIONED else "asset"
        return reverse(f"admin:inventory_{model}_change", args=[target.pk])

    def assign(self, employee=None):
        from assignments.services import create_assignment
        return create_assignment(asset_id=self.asset.pk, employee_id=(employee or self.employee).pk,
                                 assigned_by=self.user, initial_condition="Buen estado")

    def test_card_combines_assignment_return_and_maintenance_without_invented_closure(self):
        from assignments.services import return_assignment
        from maintenance.models import MaintenanceRecord, MaintenanceType
        assignment = self.assign()
        return_assignment(assignment_id=assignment.pk, condition="Recibido", returned_by=self.user)
        MaintenanceRecord.objects.create(asset=self.asset, reported_by=self.user,
                                         type=MaintenanceType.CORRECTIVE, description="Revisión sintética")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/inventory/asset/change_form.html")
        timeline = response.context["asset_timeline"]
        self.assertEqual(timeline["page"].paginator.count, 3)
        self.assertEqual({row["event_kind"] for row in timeline["rows"]}, {"assignment", "return", "maintenance"})
        self.assertContains(response, "Auditoría técnica de cambios")
        self.assertContains(response, "Revisión sintética")
        self.assertContains(response, "Sin responsable registrado")
        dates = [row["event_date"] for row in timeline["rows"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_search_finds_only_current_custodian_and_hostname(self):
        from assignments.services import return_assignment
        from inventory.models import AssetNetwork
        first = self.assign()
        return_assignment(assignment_id=first.pk, condition="Recibido")
        current = Employee.objects.create(company=self.company, full_name="Persona nueva")
        self.assign(current)
        AssetNetwork.objects.create(asset=self.asset, hostname="host-card-001")
        model_admin = admin.site._registry[Asset]
        request = RequestFactory().get("/")
        request.user = self.user
        qs = model_admin.get_queryset(request)
        for term in ("Persona nueva", "host-card-001", "CARD-001"):
            results, _ = model_admin.get_search_results(request, qs, term)
            self.assertTrue(results.filter(pk=self.asset.pk).exists())
        results, _ = model_admin.get_search_results(request, qs, "Persona vigente")
        self.assertFalse(results.filter(pk=self.asset.pk).exists())

    def test_card_hides_related_data_without_source_permissions(self):
        from django.contrib.auth.models import Permission
        from maintenance.models import MaintenanceRecord, MaintenanceType
        from accounts.models import Role
        self.assign()
        MaintenanceRecord.objects.create(asset=self.asset, reported_by=self.user,
                                         type=MaintenanceType.CORRECTIVE, description="DETALLE RESTRINGIDO")
        viewer = User.objects.create_user(username="card_viewer", role="OTHER", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="inventory", codename="view_asset"))
        self.client.force_login(viewer)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["asset_timeline"]["page"].paginator.count, 0)
        self.assertNotContains(response, "DETALLE RESTRINGIDO")
        self.assertNotContains(response, self.employee.full_name)
        self.assertContains(response, "Sin permiso para consultar custodia")

    def test_card_requires_inventory_permission(self):
        viewer = User.objects.create_user(username="no_card_permission", is_staff=True)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_pagination_has_complete_counts_and_no_duplicates(self):
        from assignments.services import return_assignment
        for _ in range(14):
            assignment = self.assign()
            return_assignment(assignment_id=assignment.pk, condition="Recibido")
        first = self.client.get(self.url())
        second = self.client.get(self.url(), {"timeline_page": 2})
        self.assertContains(first, '?timeline_page=2#asset-timeline')
        self.assertContains(second, 'data-itam-tab="asset-timeline" aria-selected="true"')
        self.assertContains(second, 'data-itam-tab="asset-summary" aria-selected="false"')
        a, b = first.context["asset_timeline"], second.context["asset_timeline"]
        self.assertEqual(a["page"].paginator.count, 28)
        self.assertEqual(len(a["rows"]), 25)
        self.assertEqual(len(b["rows"]), 3)
        keys = [(row["event_kind"], row["event_id"]) for row in a["rows"] + b["rows"]]
        self.assertEqual(len(set(keys)), 28)

    def test_decommissioned_card_and_links_use_correct_proxy(self):
        from inventory.navigation import asset_link
        from core.testing import complete_decommission
        from django.urls import reverse

        ticket = complete_decommission(self.asset)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ficha del activo")
        self.assertContains(response, "Trámite de baja registrado")
        self.assertNotContains(response, "Mantenimiento registrado")
        row, = response.context["asset_timeline"]["rows"]
        self.assertEqual(row["event_kind"], "decommission")
        self.assertEqual(row["event_date"], ticket.created_at)
        self.assertEqual(row["url"], reverse("admin:maintenance_decommission_change", args=[ticket.pk]))
        self.assertEqual(self.client.get(row["url"]).status_code, 200)
        self.assertContains(response, "Cronología operativa", count=1)
        request = RequestFactory().get("/")
        request.user = self.user
        self.assertIn(self.url(), str(asset_link(request, self.asset, admin.site)))
        from django.contrib.auth.models import Permission
        viewer = User.objects.create_user(username="decommissioned_viewer", role="OTHER", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="inventory", codename="view_decommissionedasset",
        ))
        self.client.force_login(viewer)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Habilitar Edición Manual")
        request.user = User.objects.create_user(username="no_inventory_link", is_staff=True)
        self.assertNotIn("href=", str(asset_link(request, self.asset, admin.site)))

    def test_card_escapes_events_and_labels(self):
        from maintenance.models import MaintenanceRecord, MaintenanceType
        self.employee.full_name = "<script>synthetic()</script>"
        self.employee.save()
        self.assign()
        MaintenanceRecord.objects.create(asset=self.asset, reported_by=self.user,
                                         type=MaintenanceType.CORRECTIVE, description='<img src=x onerror="synthetic()">')
        response = self.client.get(self.url())
        self.assertNotContains(response, "<script>synthetic()</script>")
        self.assertNotContains(response, '<img src=x')
        self.assertContains(response, "&lt;script&gt;")

    def test_return_without_date_is_not_given_an_invented_event(self):
        Assignment.objects.create(asset=self.asset, employee=self.employee, assigned_by=self.user,
                                  initial_condition="Migración", status=AssignmentStatus.RETURNED)
        response = self.client.get(self.url())
        self.assertEqual(response.context["asset_timeline"]["missing_return_dates"], 1)
        self.assertEqual(response.context["asset_timeline"]["page"].paginator.count, 1)
        self.assertContains(response, "devoluciones sin fecha registrada")

    def test_assignment_and_maintenance_lists_link_to_asset_card(self):
        from django.urls import reverse
        from maintenance.models import MaintenanceRecord, MaintenanceType
        self.assign()
        MaintenanceRecord.objects.create(asset=self.asset, reported_by=self.user,
                                         type=MaintenanceType.CORRECTIVE, description="Prueba")
        for route in ("admin:assignments_assignment_changelist", "admin:maintenance_maintenancerecord_changelist"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.url())
