from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import Role, User
from assignments.models import AssignmentStatus, OffboardingRecord, OffboardingRecordItem
from assignments.services import create_assignment
from inventory.models import Asset, AssetStatus, Category
from organizations.models import Company
from .models import Employee, EmployeeStatus


class OffboardingAuthorizationTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(username="offboarding_operator", password="Test-4826!")
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
        user = self.user(Role.TECHNOLOGY, True)
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
