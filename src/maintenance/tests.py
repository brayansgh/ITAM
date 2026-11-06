import tempfile

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from inventory.models import Asset, Category
from organizations.models import Company
from .admin import MaintenanceDocumentForm
from .models import MaintenanceDocument, MaintenanceRecord, MaintenanceType


class PrivateMaintenanceDocumentTests(TransactionTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.user = User.objects.create_user(username="document_reader", is_staff=True)
        company = Company.objects.create(name="Prueba", code="DOC")
        category = Category.objects.create(name="Prueba")
        asset = Asset.objects.create(asset_tag="DOC-001", company=company, category=category)
        record = MaintenanceRecord.objects.create(
            asset=asset, reported_by=self.user, type=MaintenanceType.PREVENTIVE,
            description="Prueba",
        )
        self.document = MaintenanceDocument.objects.create(
            maintenance=record, document=ContentFile(b"%PDF-1.4 synthetic", name="synthetic.pdf")
        )
        self.url = reverse("admin:maintenance_document_download", args=[self.document.pk])

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_staff_without_permission_is_denied(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authorized_staff_receives_document(self):
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="maintenance", codename="view_maintenancerecord"
        ))
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 synthetic")
        finally:
            response.close()

    def test_form_links_to_protected_download(self):
        html = str(MaintenanceDocumentForm(instance=self.document)["document"])
        self.assertIn(self.url, html)
        self.assertNotIn("/media/", html)


from django.core.exceptions import ValidationError
from django.test import TestCase
from unittest.mock import patch
from assignments.services import create_assignment, return_assignment
from assignments.models import AssignmentStatus
from employees.models import Employee
from inventory.models import AssetStatus
from .models import MaintenanceStatus


class MaintenanceTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="transition_operator")
        company = Company.objects.create(name="Prueba", code="TRANS")
        category = Category.objects.create(name="Prueba")
        self.asset = Asset.objects.create(asset_tag="TRANS-001", company=company, category=category)
        self.employee = Employee.objects.create(company=company, full_name="Persona sintética")

    def assign(self):
        return create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                 assigned_by=self.user, initial_condition="Buen estado")

    def ticket(self, **kwargs):
        data = dict(asset=self.asset, type=MaintenanceType.CORRECTIVE,
                    reported_by=self.user, description="Prueba")
        data.update(kwargs)
        obj = MaintenanceRecord(**data)
        obj._history_user = self.user
        obj.save()
        return obj

    def status(self):
        self.asset.refresh_from_db()
        return self.asset.status

    def test_repair_preserves_custody_and_closure_restores_assigned(self):
        assignment = self.assign()
        before = assignment.history.count()
        ticket = self.ticket()
        self.assertEqual(self.status(), AssetStatus.IN_MAINTENANCE)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.ACTIVE)
        self.assertIsNone(assignment.returned_at)
        self.assertEqual(assignment.history.count(), before)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        self.assertEqual(self.status(), AssetStatus.ASSIGNED)
        self.assertEqual(self.asset.history.first().history_user, self.user)

    def test_closing_one_of_two_tickets_keeps_unavailable(self):
        first, second = self.ticket(), self.ticket()
        first.status = MaintenanceStatus.COMPLETED
        first.save()
        self.assertEqual(self.status(), AssetStatus.IN_MAINTENANCE)
        second.status = MaintenanceStatus.CANCELLED
        second.save()
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)

    def test_return_during_repair_records_evidence_without_freeing_asset(self):
        assignment = self.assign()
        ticket = self.ticket()
        return_assignment(assignment_id=assignment.pk, condition="Recibido para reparación", returned_by=self.user)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.RETURNED)
        self.assertIsNotNone(assignment.returned_at)
        self.assertEqual(assignment.return_condition, "Recibido para reparación")
        self.assertEqual(self.status(), AssetStatus.IN_MAINTENANCE)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)

    def test_ticket_closure_does_not_reactivate_terminal_states(self):
        for state in (AssetStatus.RETIRED, AssetStatus.LOST, AssetStatus.IN_TRANSIT):
            with self.subTest(state=state):
                self.asset.status = state
                self.asset.save()
                ticket = self.ticket()
                ticket.status = MaintenanceStatus.COMPLETED
                ticket.save()
                self.assertEqual(self.status(), state)

    def test_available_and_decommission_are_denied_while_assigned(self):
        self.assign()
        for status in (AssetStatus.AVAILABLE, AssetStatus.DECOMMISSIONED):
            self.asset.refresh_from_db()
            self.asset.status = status
            with self.assertRaises(ValidationError):
                self.asset.full_clean()
            with self.assertRaises(ValidationError):
                self.asset.save()
            self.assertEqual(self.status(), AssetStatus.ASSIGNED)

    def test_manual_release_is_denied_with_open_ticket(self):
        self.ticket()
        self.asset.refresh_from_db()
        self.asset.status = AssetStatus.AVAILABLE
        with self.assertRaises(ValidationError):
            self.asset.save()
        self.assertEqual(self.status(), AssetStatus.IN_MAINTENANCE)

    def test_decommission_ticket_with_custody_rolls_back(self):
        self.assign()
        before = MaintenanceRecord.history.count()
        with self.assertRaises(ValidationError):
            self.ticket(type=MaintenanceType.DECOMMISSION, status=MaintenanceStatus.COMPLETED, resolution_notes="Baja sintética")
        self.assertFalse(MaintenanceRecord.objects.exists())
        self.assertEqual(MaintenanceRecord.history.count(), before)
        self.assertEqual(self.status(), AssetStatus.ASSIGNED)

    def test_failed_sync_rolls_back_ticket_and_history(self):
        before = MaintenanceRecord.history.count()
        with patch.object(Asset, "save", side_effect=RuntimeError("Fallo sintético")):
            with self.assertRaises(RuntimeError):
                self.ticket()
        self.assertFalse(MaintenanceRecord.objects.exists())
        self.assertEqual(MaintenanceRecord.history.count(), before)
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)

    def test_reassignment_of_existing_ticket_is_rejected(self):
        ticket = self.ticket()
        other = Asset.objects.create(asset_tag="TRANS-002", company=self.asset.company, category=self.asset.category)
        ticket.asset = other
        with self.assertRaises(ValidationError):
            ticket.save()
        ticket.refresh_from_db()
        self.assertEqual(ticket.asset_id, self.asset.pk)
        other.refresh_from_db()
        self.assertEqual(other.status, AssetStatus.AVAILABLE)

    def test_deleting_ticket_recalculates_remaining_repairs(self):
        first, second = self.ticket(), self.ticket()
        first.delete()
        self.assertEqual(self.status(), AssetStatus.IN_MAINTENANCE)
        second.delete()
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)

    def test_cancelled_decommission_does_not_disable_available_asset(self):
        self.ticket(type=MaintenanceType.DECOMMISSION, status=MaintenanceStatus.CANCELLED)
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)

    def test_closed_ticket_cannot_be_reopened(self):
        ticket = self.ticket()
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)
        ticket.status = MaintenanceStatus.IN_PROGRESS
        with self.assertRaises(ValidationError):
            ticket.save()
        self.assertEqual(self.status(), AssetStatus.AVAILABLE)


class ConcurrentMaintenanceTests(TransactionTestCase):
    def test_simultaneous_closures_leave_asset_available_without_extra_tickets(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        user = User.objects.create_user(username="concurrent_operator")
        company = Company.objects.create(name="Prueba", code="CONCURRENT")
        category = Category.objects.create(name="Prueba")
        asset = Asset.objects.create(asset_tag="CONCURRENT-001", company=company, category=category)
        tickets = [MaintenanceRecord.objects.create(
            asset=asset, reported_by=user, type=MaintenanceType.CORRECTIVE, description="Prueba",
        ) for _ in range(2)]
        barrier = Barrier(2)

        def close(pk):
            try:
                ticket = MaintenanceRecord.objects.get(pk=pk)
                barrier.wait(timeout=10)
                ticket.status = MaintenanceStatus.COMPLETED
                ticket.save()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(close, ticket.pk) for ticket in tickets]
            for future in futures:
                future.result(timeout=20)
        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.AVAILABLE)
        self.assertEqual(MaintenanceRecord.objects.count(), 2)
        self.assertFalse(MaintenanceRecord.objects.exclude(status=MaintenanceStatus.COMPLETED).exists())
