from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from assignments.models import Assignment
from employees.models import Employee
from inventory.models import Asset, AssetNetwork, AssetSpecs, Category
from maintenance.models import MaintenanceDocument, MaintenanceRecord, MaintenanceStatus, MaintenanceType
from organizations.models import Company

from .management.commands.configure_itam_groups import AUDITOR_GROUP, SUPPORT_GROUP
from .models import Role, User


def support_operator(administrator):
    call_command("configure_itam_groups", apply=True, actor=administrator.username, stdout=StringIO())
    operator = User.objects.create_user(username="support_profile", role=Role.TECHNOLOGY, is_staff=True)
    operator.groups.add(Group.objects.get(name=SUPPORT_GROUP))
    return operator


class AccessProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_superuser(username="profile_admin", role=Role.ADMINISTRATOR)
        cls.support = support_operator(cls.administrator)
        cls.auditor = User.objects.create_user(username="audit_profile", role=Role.CONSULTATION, is_staff=True)
        cls.auditor.groups.add(Group.objects.get(name=AUDITOR_GROUP))
        cls.company = Company.objects.create(name="Compañía de prueba", code="ACE")
        cls.category = Category.objects.create(name="Equipo")
        cls.asset = Asset.objects.create(company=cls.company, category=cls.category, asset_tag="TEST-001")
        cls.ticket = MaintenanceRecord.objects.create(
            asset=cls.asset, reported_by=cls.administrator, description="Revisión",
        )

    def test_preview_is_read_only_and_application_is_audited_and_idempotent(self):
        group = Group.objects.get(name=SUPPORT_GROUP)
        version = group.history.first()
        self.assertEqual(version.history_user, self.administrator)
        self.assertTrue(version.permissions.exists())
        group.permissions.clear()
        count = group.history.count()
        output = StringIO()
        call_command("configure_itam_groups", stdout=output)
        self.assertIn("inventory.add_asset", output.getvalue())
        self.assertFalse(group.permissions.exists())
        self.assertEqual(group.history.count(), count)
        call_command("configure_itam_groups", apply=True, actor=self.administrator.username, stdout=StringIO())
        count = group.history.count()
        call_command("configure_itam_groups", apply=True, actor=self.administrator.username, stdout=StringIO())
        self.assertEqual(group.history.count(), count)

    def test_support_creates_employee_and_assignment_and_closes_maintenance(self):
        self.client.force_login(self.support)
        response = self.client.post(reverse("admin:maintenance_maintenancerecord_change", args=[self.ticket.pk]), {
            "asset": self.asset.pk, "reported_by": self.administrator.pk,
            "type": MaintenanceType.CORRECTIVE, "description": "Revisión",
            "status": MaintenanceStatus.COMPLETED, "resolution_notes": "Trabajo verificado",
            "documents-TOTAL_FORMS": "0", "documents-INITIAL_FORMS": "0", "_save": "Guardar",
        })
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, MaintenanceStatus.COMPLETED)

        response = self.client.post(reverse("admin:employees_employee_add"), {
            "company": self.company.pk, "full_name": "Persona sintética",
            "document_type": "CC", "status": "ACTIVE", "_save": "Guardar",
        })
        self.assertEqual(response.status_code, 302)
        employee = Employee.objects.get()
        response = self.client.post(reverse("admin:assignments_assignment_add"), {
            "asset": self.asset.pk, "employee": employee.pk, "initial_condition": "Bueno", "_save": "Guardar",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Assignment.objects.get().assigned_by, self.support)

    def test_support_cannot_administer_accounts_catalogs_or_imports(self):
        self.client.force_login(self.support)
        for name in ("accounts_user_changelist", "auth_group_changelist", "data_imports_stagingasset_changelist"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"admin:{name}")).status_code, 403)
        for name in ("inventory_brand_add", "organizations_company_add"):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(f"admin:{name}"), {}).status_code, 403)
        delete_asset = reverse("admin:inventory_asset_delete", args=[self.asset.pk])
        self.assertEqual(self.client.post(delete_asset, {"post": "yes"}).status_code, 403)

    def test_auditor_reads_evidence_but_cannot_modify_or_see_restricted_details(self):
        specs = AssetSpecs.objects.create(asset=self.asset, processor="Procesador inicial")
        specs.processor = "Procesador sintético"
        specs.save()
        network = AssetNetwork.objects.create(asset=self.asset, hostname="hostname-inicial")
        network.hostname = "hostname-privado-sintetico"
        network.save()
        self.client.force_login(self.auditor)
        self.assertTrue(all(".view_" in perm for perm in self.auditor.get_all_permissions()))
        for name in ("inventory_asset", "assignments_assignment", "assignments_offboardingrecord",
                     "maintenance_maintenancerecord", "inventory_decommissionedasset"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200)
        for name in ("employees_employee", "accounts_user", "auth_group", "data_imports_stagingasset"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 403)
        for name, pk in (("inventory_asset", self.asset.pk), ("maintenance_maintenancerecord", self.ticket.pk)):
            with self.subTest(name=name):
                url = reverse(f"admin:{name}_change", args=[pk])
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:assignments_assignment_add"), {}).status_code, 403)

        history = self.client.get(reverse("admin:inventory_asset_history", args=[self.asset.pk]))
        self.assertEqual(history.context["related_count"], 2)
        self.assertContains(history, "Procesador sintético")
        self.assertNotContains(history, "hostname-privado-sintetico")
        results = self.client.get(reverse("admin:inventory_asset_changelist"), {"q": "hostname-privado-sintetico"})
        self.assertEqual(results.context["cl"].result_count, 0)



class AuditorDownloadTests(TransactionTestCase):
    def test_auditor_can_download_a_protected_maintenance_pdf(self):
        administrator = User.objects.create_superuser(username="download_admin", role=Role.ADMINISTRATOR)
        call_command("configure_itam_groups", apply=True, actor=administrator.username, stdout=StringIO())
        auditor = User.objects.create_user(username="download_auditor", is_staff=True)
        auditor.groups.add(Group.objects.get(name=AUDITOR_GROUP))
        self.client.force_login(auditor)
        company = Company.objects.create(name="Compañía de prueba", code="ACE")
        category = Category.objects.create(name="Equipo")
        asset = Asset.objects.create(company=company, category=category, asset_tag="TEST-001")
        ticket = MaintenanceRecord.objects.create(asset=asset, reported_by=administrator, description="Revisión")
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            document = MaintenanceDocument.objects.create(
                maintenance=ticket, document=ContentFile(b"%PDF synthetic", name="evidencia.pdf"),
            )
            download = self.client.get(reverse("admin:maintenance_document_download", args=[document.pk]))
            self.assertEqual(download.status_code, 200)
            try:
                self.assertEqual(b"".join(download.streaming_content), b"%PDF synthetic")
            finally:
                download.close()
