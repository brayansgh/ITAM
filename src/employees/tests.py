from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import Role, User
from accounts.test_access_profiles import support_operator
from assignments.models import AssignmentStatus, OffboardingRecord, OffboardingRecordItem
from assignments.services import create_assignment
from inventory.models import Asset, AssetStatus, Category
from organizations.models import Company
from .models import Employee, EmployeeStatus


class OffboardingAuthorizationTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(username="offboarding_operator", password="Test-4826!", role=Role.ADMINISTRATOR)
        company = Company.objects.create(name="Prueba", code="SEC")
        category = Category.objects.create(name="Prueba")
        self.employee = Employee.objects.create(company=company, full_name="Persona de prueba")
        self.asset = Asset.objects.create(company=company, category=category, asset_tag="SEC-001")
        self.assignment = create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                            assigned_by=self.operator, initial_condition="Buen estado")
        self.employee.status = EmployeeStatus.RETIRO
        self.employee.save()
        self.url = reverse("admin:employees_employee_process_offboarding", args=[self.employee.pk])
        self.data = {
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-assignment_id": str(self.assignment.pk), "items-0-selected": "on",
            "items-0-condition": "Recibido en buen estado",
        }
        self.permission = Permission.objects.get(content_type__app_label="employees", codename="change_employee")

    def user(self, role, permission=False):
        user = User.objects.create_user(username=f"security_{User.objects.count()}", role=role, is_staff=True)
        if permission:
            user.user_permissions.add(self.permission)
        return user

    def test_denied_roles_cannot_read_or_mutate_even_with_direct_url(self):
        for role, permission in [(Role.CONSULTATION, False), (Role.CONSULTATION, True),
                                 (Role.TECHNOLOGY, False), (Role.ADMINISTRATOR, False)]:
            with self.subTest(role=role, permission=permission):
                user = self.user(role, permission)
                self.client.force_login(user)
                versions = self.assignment.history.count()
                with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf") as pdf:
                    self.assertEqual(self.client.get(self.url).status_code, 403)
                    self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
                    pdf.assert_not_called()
                self.assignment.refresh_from_db()
                self.asset.refresh_from_db()
                self.assertEqual(self.assignment.status, AssignmentStatus.ACTIVE)
                self.assertEqual(self.asset.status, AssetStatus.ASSIGNED)
                self.assertEqual(self.assignment.history.count(), versions)
                self.assertFalse(OffboardingRecord.objects.exists())
                self.assertFalse(OffboardingRecordItem.objects.exists())

    def test_allowed_roles_with_permission_can_open_form(self):
        for role in (Role.ADMINISTRATOR, Role.TECHNOLOGY):
            with self.subTest(role=role):
                self.client.force_login(self.user(role, True))
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_technology_can_return_assets_and_preserve_audit(self):
        user = support_operator(self.operator)
        self.client.force_login(user)
        with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf",
                   return_value=HttpResponse(b"%PDF synthetic", content_type="application/pdf")) as pdf:
            self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
            pdf.assert_called_once()
        self.assignment.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.RETURNED)
        self.assertIsNotNone(self.assignment.returned_at)
        self.assertEqual(self.assignment.return_condition, "Recibido en buen estado")
        self.assertEqual(self.assignment.history.first().history_user, user)
        self.assertEqual(self.asset.status, AssetStatus.AVAILABLE)
        self.assertEqual(OffboardingRecord.objects.get().received_by, user)
        self.assertEqual(OffboardingRecordItem.objects.get().assignment, self.assignment)

    def test_failed_pdf_rolls_back_retired_employee_return(self):
        self.client.force_login(self.operator)
        with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf", side_effect=OSError):
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "La devolución no se registró.")
        self.assignment.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.ACTIVE)
        self.assertEqual(self.asset.status, AssetStatus.ASSIGNED)
        self.assertFalse(OffboardingRecord.objects.exists())
        self.assertFalse(OffboardingRecordItem.objects.exists())

    def test_retirement_without_custody_generates_distinct_act_in_retired_list(self):
        from assignments.models import ReturnReason

        employee = Employee.objects.create(company=self.employee.company, full_name="Persona sin custodia")
        ordinary = OffboardingRecord.objects.create(
            employee=employee, received_by=self.operator, return_reason=ReturnReason.DAMAGE,
            pdf="devolucion-sintetica.pdf",
        )
        self.client.force_login(self.operator)
        url = reverse("admin:employees_employee_change", args=[employee.pk])
        data = {"full_name": employee.full_name, "company": employee.company_id, "document_type": "CC",
                "status": EmployeeStatus.RETIRO, "_save": "Guardar"}
        with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf", side_effect=OSError):
            failed = self.client.post(url, data, follow=True)
        self.assertContains(failed, "El retiro no se registró.")
        employee.refresh_from_db()
        self.assertEqual(employee.status, EmployeeStatus.ACTIVE)
        self.assertFalse(employee.offboarding_records.filter(return_reason="").exists())

        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            response = self.client.post(url, data)
            record = employee.offboarding_records.get(return_reason="")
            self.assertTrue(record.pdf)
            self.assertIn("Acta_Desvinculacion_", record.pdf.name)
            self.assertFalse(record.items.exists())
            receipt_url = reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk])
            self.assertRedirects(response, receipt_url)
            self.assertContains(self.client.get(receipt_url), "Resumen de desvinculación")
            retired = self.client.get(reverse("admin:employees_retiredemployee_changelist"))
            self.assertEqual(retired.context["title"], "Empleados retirados")
            self.assertContains(retired, "Actas de desvinculación")
            self.assertContains(retired, receipt_url)
            self.assertNotContains(retired, reverse("admin:assignments_offboardingrecord_receipt", args=[ordinary.pk]))
            self.assertNotContains(retired, "Historial de devoluciones")

    def test_profile_starts_retirement_and_continues_to_asset_reception(self):
        self.employee.status = EmployeeStatus.ACTIVE
        self.employee.save(update_fields=["status"])
        profile = reverse("admin:employees_employee_change", args=[self.employee.pk])
        start = reverse("admin:employees_employee_start_offboarding", args=[self.employee.pk])

        reader = self.user(Role.CONSULTATION, True)
        self.client.force_login(reader)
        self.assertNotContains(self.client.get(profile), start)
        self.assertEqual(self.client.post(start).status_code, 403)

        support = support_operator(self.operator)
        self.client.force_login(support)
        self.assertContains(self.client.get(profile), f'<a href="{start}">Desvinculación</a>', html=True)
        self.assertContains(self.client.get(start), "Confirmar desvinculación")
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.status, EmployeeStatus.ACTIVE)

        self.assertRedirects(self.client.post(start), self.url)
        self.employee.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.employee.status, EmployeeStatus.RETIRO)
        self.assertEqual(self.employee.history.first().history_user, support)
        self.assertEqual(self.assignment.status, AssignmentStatus.ACTIVE)
        self.assertFalse(self.employee.offboarding_records.exists())
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            response = self.client.post(self.url, self.data)
            record = self.employee.offboarding_records.get()
            self.assertTrue(record.pdf)
            self.assertRedirects(response, reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk]))

    def test_profile_retirement_without_custody_rolls_back_if_pdf_fails(self):
        employee = Employee.objects.create(company=self.employee.company, full_name="Persona sin activos")
        start = reverse("admin:employees_employee_start_offboarding", args=[employee.pk])
        self.client.force_login(self.operator)
        with patch("inventory.offboarding_pdf.generate_and_save_offboarding_pdf", side_effect=OSError):
            response = self.client.post(start, follow=True)
        self.assertContains(response, "El retiro no se registró")
        employee.refresh_from_db()
        self.assertEqual(employee.status, EmployeeStatus.ACTIVE)
        self.assertFalse(employee.offboarding_records.exists())

        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            response = self.client.post(start)
            record = employee.offboarding_records.get()
            self.assertTrue(record.pdf)
            self.assertRedirects(response, reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk]))
            self.assertEqual(self.client.post(start).status_code, 404)
            self.assertEqual(employee.offboarding_records.count(), 1)

    def test_superuser_exception_is_preserved(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_nonstaff_and_inactive_users_are_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for staff, active in [(False, True), (True, False)]:
            user = User.objects.create_user(username=f"blocked_{User.objects.count()}",
                                            role=Role.ADMINISTRATOR, is_staff=staff, is_active=active)
            self.client.force_login(user)
            self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        self.assertFalse(OffboardingRecord.objects.exists())

    def test_list_hides_action_for_unauthorized_user(self):
        model_admin = admin.site._registry[Employee]
        request = RequestFactory().get("/")
        request.user = self.user(Role.CONSULTATION, True)
        self.assertNotIn("process_offboarding", model_admin.get_list_display(request))
        request.user = self.user(Role.TECHNOLOGY, True)
        self.assertIn("process_offboarding", model_admin.get_list_display(request))
