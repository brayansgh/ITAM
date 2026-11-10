from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from accounts.test_access_profiles import support_operator
from assignments.models import AssignmentStatus, OffboardingRecord, ReturnReason
from assignments.services import create_assignment
from inventory.models import Asset, AssetNetwork, AssetStatus, Category
from maintenance.models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
from organizations.models import Company
from .models import Employee, EmployeeStatus


class ActiveReturnsTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=media.name))
        self.user = User.objects.create_superuser(username="return_operator", password=None, role=Role.ADMINISTRATOR)
        self.company = Company.objects.create(name="Compañía de prueba", code="RET")
        self.category = Category.objects.create(name="Equipo de prueba")
        self.employee = Employee.objects.create(company=self.company, full_name="Empleado de prueba")
        self.assignments = [self.assign(self.employee, index) for index in range(3)]
        self.client.force_login(self.user)
        self.url = reverse("admin:employees_employee_return_assets", args=[self.employee.pk])
        self.data = {
            "assignments": [str(assignment.pk) for assignment in self.assignments[:2]],
            "reason": ReturnReason.DAMAGE,
            "condition": "Recibido con daño en carcasa",
        }

    def assign(self, employee, index):
        asset = Asset.objects.create(company=self.company, category=self.category, asset_tag=f"RET-{index:03}")
        return create_assignment(asset_id=asset.pk, employee_id=employee.pk, assigned_by=self.user,
                                 initial_condition="Buen estado")

    def test_profile_groups_only_permitted_actions_and_keeps_edit_form(self):
        profile_url = reverse("admin:employees_employee_change", args=[self.employee.pk])
        history_url = reverse("admin:employees_employee_history", args=[self.employee.pk])
        page = self.client.get(profile_url)
        self.assertContains(page, '<h2 id="employee-name">Empleado de prueba</h2>', html=True)
        self.assertContains(page, self.employee.full_name, count=1)
        self.assertContains(page, "<summary>Acciones</summary>", html=True)
        self.assertContains(page, f'<a href="{self.url}">Devolver activos</a>', html=True)
        loan_url = reverse("admin:assignments_assignment_loan") + f"?employee={self.employee.pk}"
        self.assertContains(page, f'<a href="{loan_url}">Prestar activos</a>', html=True)
        loan = self.client.get(loan_url)
        self.assertEqual(loan.context["form"].initial["employee"], str(self.employee.pk))
        self.assertContains(page, f'<a href="{history_url}">Ver histórico</a>', count=1, html=True)
        self.assertContains(page, "button itam-primary")
        self.assertContains(page, "itam-employee-secondary")
        edit_page = self.client.get(profile_url, {"editar": 1})
        self.assertContains(edit_page, 'name="full_name"')
        self.assertNotContains(edit_page, 'id="employee-name"')

        reader = User.objects.create_user(username="employee_reader", is_staff=True, role=Role.CONSULTATION)
        reader.user_permissions.add(Permission.objects.get(
            content_type__app_label="employees", codename="view_employee",
        ))
        self.client.force_login(reader)
        page = self.client.get(profile_url)
        self.assertContains(page, "Solo consulta")
        self.assertNotContains(page, "Asignar activo")
        self.assertNotContains(page, "Editar empleado")
        self.assertNotContains(page, "Devolver activos")
        self.assertNotContains(page, "Prestar activos")

    def test_return_options_include_equipment_details_and_reject_loan_reason_for_ordinary_custody(self):
        asset = self.assignments[0].asset
        asset.legacy_asset_tag = "PL-101"
        asset.serial_number = "SERIE-101"
        asset.save(update_fields=["legacy_asset_tag", "serial_number"])
        AssetNetwork.objects.create(asset=asset, hostname="EQUIPO-101")
        page = self.client.get(self.url)
        for label in ("PL-101", "RET-000", "Equipo de prueba", "EQUIPO-101", "SERIE-101", "Fin del préstamo"):
            self.assertContains(page, label)
        result = self.client.post(self.url, {**self.data, "reason": ReturnReason.LOAN_END})
        self.assertContains(result, "Selecciona únicamente activos prestados")
        self.assertFalse(OffboardingRecord.objects.exists())
        self.assertEqual(self.assignments[0].asset.assignments.get().status, AssignmentStatus.ACTIVE)

    def test_one_pdf_contains_all_selected_assets_and_keeps_employee_active(self):
        self.user = support_operator(self.user)
        self.client.force_login(self.user)
        from inventory import offboarding_pdf

        self.assertContains(self.client.get(reverse("admin:employees_employee_changelist")), self.url)
        with patch.object(offboarding_pdf, "render_to_string", wraps=offboarding_pdf.render_to_string) as rendered:
            response = self.client.post(self.url, self.data)
        record = OffboardingRecord.objects.get()
        receipt = reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk])
        self.assertRedirects(response, receipt, fetch_redirect_response=False)
        pdf = reverse("admin:assignments_offboardingrecord_view_pdf", args=[record.pk])
        summary = self.client.get(receipt)
        self.assertContains(summary, "Resumen de devolución")
        self.assertContains(summary, "Devolución registrada")
        self.assertContains(summary, "Activos recibidos")
        self.assertContains(summary, "data-itam-return-pdf")
        self.assertContains(summary, pdf)
        self.assertNotContains(self.client.get(receipt), "data-itam-return-pdf")
        profile = self.client.get(reverse("admin:employees_employee_change", args=[self.employee.pk]))
        self.assertContains(profile, pdf)
        self.assertContains(profile, "Ver asignación")
        self.assertContains(profile, "Historial de asignaciones")
        self.assertContains(profile, "Ver resumen")
        detail = self.client.get(reverse("admin:assignments_offboardingrecord_change", args=[record.pk]))
        self.assertContains(detail, "Fecha de registro")
        self.assertContains(detail, "Consultar acta de devolución")
        self.assertContains(detail, "Solo consulta")
        self.assertNotContains(detail, "Actualiza la información")
        self.assertNotContains(detail, 'name="_save"')
        self.assertContains(detail, 'class="itam-return-decommission-list"')
        self.assertEqual(self.client.post(detail.request["PATH_INFO"], {"_save": "Guardar"}).status_code, 403)
        self.assertContains(detail, "Activo recibido")
        self.assertContains(self.client.get(reverse("admin:assignments_assignment_change", args=[self.assignments[0].pk])), pdf)
        with record.pdf.open("rb") as file:
            self.assertTrue(file.read(4).startswith(b"%PDF"))
        self.assertTrue(record.pdf.storage.exists(record.pdf.name))
        self.assertEqual(record.return_reason, ReturnReason.DAMAGE)
        self.assertEqual(set(record.items.values_list("assignment_id", flat=True)),
                         {assignment.pk for assignment in self.assignments[:2]})
        self.assertEqual(record.history.first().history_user, self.user)
        self.assertEqual(len(rendered.call_args.args[1]["assignments"]), 2)
        html = offboarding_pdf.render_to_string(*rendered.call_args.args)
        self.assertIn("ACTA DE DEVOLUCIÓN DE ACTIVOS", html)
        self.assertNotIn("CHECKLIST DE DESVINCULACIÓN", html)
        self.assertNotIn(self.assignments[2].asset.asset_tag, html)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.status, EmployeeStatus.ACTIVE)
        self.assignments[2].refresh_from_db()
        self.assertEqual(self.assignments[2].status, AssignmentStatus.ACTIVE)
        for assignment in self.assignments[:2]:
            assignment.refresh_from_db()
            self.assertEqual(assignment.status, AssignmentStatus.RETURNED)
            self.assertEqual(assignment.history.first().history_user, self.user)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 200)
        self.assertEqual(OffboardingRecord.objects.count(), 1)

    def test_decommission_can_link_existing_and_create_open_ticket_in_same_return(self):
        first, second, _ = self.assignments
        existing = MaintenanceRecord.objects.create(
            asset=first.asset, type=MaintenanceType.DECOMMISSION, reported_by=self.user, description="Baja en trámite",
        )
        response = self.client.post(self.url, {**self.data, "request_decommission": "on"})
        self.assertEqual(response.status_code, 302)
        record = OffboardingRecord.objects.get()
        self.assertEqual(MaintenanceRecord.objects.count(), 2)
        existing.refresh_from_db()
        self.assertEqual(existing.return_item.assignment_id, first.pk)
        self.assertEqual(existing.return_item.offboarding_record_id, record.pk)
        ticket = MaintenanceRecord.objects.get(asset=second.asset)
        self.assertEqual(ticket.return_item.assignment_id, second.pk)
        self.assertEqual(ticket.status, MaintenanceStatus.OPEN)
        self.assertEqual(Asset.objects.get(pk=second.asset_id).status, AssetStatus.IN_MAINTENANCE)
        ticket.status = MaintenanceStatus.COMPLETED
        with self.assertRaises(ValidationError):
            ticket.save()
        ticket.resolution_notes = "Disposición final de prueba."
        ticket.save()
        self.assertEqual(Asset.objects.get(pk=second.asset_id).status, AssetStatus.DECOMMISSIONED)
        self.assertContains(self.client.get(reverse("admin:maintenance_maintenancerecord_change", args=[ticket.pk])),
                            "Ver acta de devolución de origen")

    def test_can_start_decommission_later_for_one_asset_from_the_act(self):
        self.client.post(self.url, self.data)
        record = OffboardingRecord.objects.get()
        item = record.items.get(assignment=self.assignments[0])
        route = reverse("admin:assignments_offboardingrecord_link_decommission", args=[record.pk, item.pk])
        act = self.client.get(reverse("admin:assignments_offboardingrecord_change", args=[record.pk]))
        self.assertContains(act, route)
        docs = self.client.get(reverse("admin:itam_documents"), {"tipo": "devolucion"})
        self.assertContains(docs, "Ver acta")
        self.assertEqual(self.client.get(route).status_code, 405)
        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(MaintenanceRecord.objects.get().return_item_id, item.pk)

    def test_rejects_foreign_custody_and_missing_condition(self):
        other = Employee.objects.create(company=self.company, full_name="Otra persona")
        other_assignment = self.assign(other, 3)
        response = self.client.post(self.url, {**self.data, "assignments": [str(other_assignment.pk)]})
        self.assertTrue(response.context["form"].errors["assignments"])
        response = self.client.post(self.url, {**self.data, "condition": " "})
        self.assertTrue(response.context["form"].errors["condition"])
        self.assertFalse(OffboardingRecord.objects.exists())

    def test_requires_roles_and_rejects_decommission_without_permission(self):
        viewer = User.objects.create_user(username="return_viewer", role=Role.CONSULTATION, is_staff=True)
        technology = User.objects.create_user(username="return_tech", role=Role.TECHNOLOGY, is_staff=True)
        permission = Permission.objects.get(content_type__app_label="employees", codename="change_employee")
        viewer.user_permissions.add(permission)
        technology.user_permissions.add(permission)
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        self.client.force_login(technology)
        self.assertEqual(self.client.post(self.url, {**self.data, "request_decommission": "on"}).status_code, 403)
        self.assertFalse(OffboardingRecord.objects.exists())
        self.assertFalse(MaintenanceRecord.objects.exists())
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 302)
        record = OffboardingRecord.objects.get()
        self.assertEqual(record.received_by, technology)
        self.assertContains(self.client.get(response.url), "Abrir acta PDF")
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(response.url).status_code, 403)
        pdf = reverse("admin:assignments_offboardingrecord_view_pdf", args=[record.pk])
        self.assertEqual(self.client.get(pdf).status_code, 403)

    def test_pdf_failure_rolls_back_custody_and_ticket(self):
        with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf", side_effect=RuntimeError):
            response = self.client.post(self.url, {**self.data, "request_decommission": "on"})
        self.assertContains(response, "La devolución no se registró")
        self.assertFalse(OffboardingRecord.objects.exists())
        self.assertFalse(MaintenanceRecord.objects.exists())
        for assignment in self.assignments:
            assignment.refresh_from_db()
            self.assertEqual(assignment.status, AssignmentStatus.ACTIVE)
            self.assertEqual(Asset.objects.get(pk=assignment.asset_id).status, AssetStatus.ASSIGNED)
