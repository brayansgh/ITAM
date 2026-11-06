import tempfile
from django.test import TestCase, override_settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.contrib import admin
from django.urls import reverse
from accounts.models import User
from organizations.models import Company
from employees.models import Employee
from assignments.services import create_assignment, return_assignment
from inventory.models import Asset, AssetStatus, Category, AssetSpecs, AssetNetwork, AssetWarranty, DecommissionedAsset
from .models import MaintenanceRecord, MaintenanceDocument, MaintenanceStatus, MaintenanceType


class ClosedLifecycleTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(MEDIA_ROOT=folder.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_superuser(username="closure_operator", password="Test-4826!")
        company = Company.objects.create(name="Empresa sintética", code="CLOSE")
        category = Category.objects.create(name="Categoría")
        self.asset = Asset.objects.create(asset_tag="CLOSE-001", company=company, category=category)
        self.client.force_login(self.user)

    def ticket(self, **kwargs):
        data = dict(asset=self.asset, reported_by=self.user, type=MaintenanceType.DECOMMISSION,
                    description="Baja sintética")
        data.update(kwargs)
        return MaintenanceRecord.objects.create(**data)

    def complete(self, ticket):
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.resolution_notes = "Entrega y disposición documentadas."
        ticket.save()
        self.asset.refresh_from_db()

    def test_pending_decommission_is_not_final_and_not_assignable(self):
        ticket = self.ticket()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.IN_MAINTENANCE)
        self.assertEqual(MaintenanceRecord.objects.count(), 1)
        employee = Employee.objects.create(company=self.asset.company, full_name="Persona")
        with self.assertRaises(ValidationError):
            create_assignment(asset_id=self.asset.pk, employee_id=employee.pk,
                              assigned_by=self.user, initial_condition="Buen estado")
        self.complete(ticket)
        self.assertEqual(self.asset.status, AssetStatus.DECOMMISSIONED)
        self.assertEqual(self.client.get(reverse("admin:inventory_asset_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:inventory_decommissionedasset_change", args=[self.asset.pk])).status_code, 200)

    def test_completion_requires_resolution_and_resolved_custody(self):
        employee = Employee.objects.create(company=self.asset.company, full_name="Persona")
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=employee.pk,
                                       assigned_by=self.user, initial_condition="Buen estado")
        ticket = self.ticket()
        ticket.status = MaintenanceStatus.COMPLETED
        with self.assertRaises(ValidationError): ticket.full_clean()
        with self.assertRaises(ValidationError): ticket.save()
        return_assignment(assignment_id=assignment.pk, condition="Recibido")
        ticket.resolution_notes = "Baja documentada"
        ticket.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.DECOMMISSIONED)

    def test_other_open_work_blocks_finalization(self):
        repair = self.ticket(type=MaintenanceType.CORRECTIVE)
        decommission = self.ticket()
        with self.assertRaises(ValidationError): self.complete(decommission)
        repair.status = MaintenanceStatus.CANCELLED
        repair.save()
        self.complete(decommission)
        self.assertEqual(self.asset.status, AssetStatus.DECOMMISSIONED)

    def test_cancelled_decommission_releases_asset_without_baja(self):
        ticket = self.ticket()
        ticket.status = MaintenanceStatus.CANCELLED
        ticket.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.AVAILABLE)
        with self.assertRaises(ValidationError): ticket.save()

    def test_completed_ticket_cannot_edit_reopen_or_delete_even_by_queryset(self):
        ticket = self.ticket()
        self.complete(ticket)
        before = ticket.history.count()
        for field, value in (("description", "Alterado"), ("status", MaintenanceStatus.OPEN)):
            ticket.refresh_from_db()
            setattr(ticket, field, value)
            with self.assertRaises(ValidationError): ticket.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            MaintenanceRecord.objects.filter(pk=ticket.pk).delete()
        self.assertEqual(ticket.history.count(), before)
        self.assertTrue(MaintenanceRecord.objects.filter(pk=ticket.pk).exists())

    def test_closed_ticket_admin_is_view_only_and_cannot_post_or_delete(self):
        ticket = self.ticket(type=MaintenanceType.CORRECTIVE)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        url = reverse("admin:maintenance_maintenancerecord_change", args=[ticket.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": MaintenanceStatus.OPEN}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:maintenance_maintenancerecord_delete", args=[ticket.pk]), {"post":"yes"}).status_code, 403)

    def test_decommissioned_asset_and_all_attachments_are_frozen(self):
        attachments = [AssetSpecs.objects.create(asset=self.asset, ram="8 GB"),
                       AssetNetwork.objects.create(asset=self.asset, hostname="test-host"),
                       AssetWarranty.objects.create(asset=self.asset, supplier="Proveedor")]
        self.complete(self.ticket())
        self.asset.observations = "Cambio bloqueado"
        with self.assertRaises(ValidationError): self.asset.save()
        with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic(): self.asset.delete()
        for obj in attachments:
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ValidationError): obj.save()
                with self.assertRaises(ValidationError), transaction.atomic(): type(obj).objects.filter(pk=obj.pk).delete()
        with self.assertRaises(ValidationError): AssetSpecs.objects.create(asset=self.asset)
        with self.assertRaises(ValidationError): self.ticket(type=MaintenanceType.CORRECTIVE)

    def test_force_edit_cannot_unlock_baja(self):
        self.complete(self.ticket())
        url = reverse("admin:inventory_decommissionedasset_change", args=[self.asset.pk]) + "?force_edit=1"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Habilitar Edición Manual")
        self.assertFalse(response.context["has_change_permission"])
        self.assertEqual(self.client.post(url, {"status": AssetStatus.AVAILABLE}).status_code, 403)
        with self.assertRaises((ValidationError, ProtectedError)), transaction.atomic(): DecommissionedAsset.objects.filter(pk=self.asset.pk).delete()

    def test_closed_documents_download_but_cannot_be_changed_or_removed(self):
        ticket = self.ticket(type=MaintenanceType.CORRECTIVE)
        document = MaintenanceDocument.objects.create(maintenance=ticket,
                    document=ContentFile(b"%PDF synthetic", name="synthetic.pdf"))
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        url = reverse("admin:maintenance_maintenancerecord_change", args=[ticket.pk])
        response = self.client.get(url)
        download = reverse("admin:maintenance_document_download", args=[document.pk])
        self.assertContains(response, download)
        self.assertNotContains(response, "/media/")
        with self.assertRaises(ValidationError): document.save()
        with self.assertRaises(ValidationError), transaction.atomic(): MaintenanceDocument.objects.filter(pk=document.pk).delete()
        with self.assertRaises(ValidationError):
            MaintenanceDocument.objects.create(maintenance=ticket, document="synthetic.pdf")
        # RequestFactory evita cerrar FileResponse dentro de TestCase (ver AGENTS).
        from django.test import RequestFactory
        request = RequestFactory().get(download); request.user = self.user
        response = admin.site._registry[MaintenanceRecord].download_document(request, document.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF synthetic")
        response.file_to_stream.close()

    def test_manual_baja_requires_completed_ticket(self):
        self.asset.status = AssetStatus.DECOMMISSIONED
        with self.assertRaises(ValidationError): self.asset.full_clean()
        with self.assertRaises(ValidationError): self.asset.save()

    def test_partial_save_cannot_hide_or_fake_a_ticket_closure(self):
        ticket = self.ticket(type=MaintenanceType.CORRECTIVE)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.description = "Solo descripción"
        ticket.save(update_fields=["description"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceStatus.OPEN)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save(update_fields=["status"])
        ticket.status = MaintenanceStatus.OPEN
        with self.assertRaises(ValidationError): ticket.save(update_fields=["status"])

    def test_saving_evidence_and_closure_together_is_a_form_error_not_partial_write(self):
        ticket = self.ticket(type=MaintenanceType.CORRECTIVE)
        document = MaintenanceDocument.objects.create(maintenance=ticket,
                    document=ContentFile(b"%PDF synthetic", name="synthetic.pdf"))
        from .admin import MaintenanceDocumentFormSet
        from django.forms.models import inlineformset_factory
        factory = inlineformset_factory(MaintenanceRecord, MaintenanceDocument,
                    formset=MaintenanceDocumentFormSet, fields=("document",), extra=0, can_delete=True)
        ticket.status = MaintenanceStatus.COMPLETED
        formset = factory(instance=ticket, prefix="documents", data={
            "documents-TOTAL_FORMS":"1", "documents-INITIAL_FORMS":"1",
            "documents-0-id":str(document.pk), "documents-0-DELETE":"on",
        })
        self.assertFalse(formset.is_valid())
        self.assertTrue(formset.non_form_errors())
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceStatus.OPEN)
        self.assertTrue(MaintenanceDocument.objects.filter(pk=document.pk).exists())

    def test_cancelled_ticket_cannot_be_deleted_by_queryset(self):
        ticket = self.ticket(type=MaintenanceType.CORRECTIVE)
        ticket.status = MaintenanceStatus.CANCELLED
        ticket.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            MaintenanceRecord.objects.filter(pk=ticket.pk).delete()
        self.assertTrue(MaintenanceRecord.objects.filter(pk=ticket.pk).exists())

    def test_completed_baja_can_be_consulted_in_audit(self):
        ticket = self.ticket()
        self.complete(ticket)
        url = reverse("admin:maintenance_maintenancerecord_history", args=[ticket.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Completado / Resuelto")


    def test_mutating_foreign_keys_in_memory_cannot_bypass_delete_protection(self):
        ticket = self.ticket()
        spec = AssetSpecs.objects.create(asset=self.asset, ram="8 GB")
        document = MaintenanceDocument.objects.create(maintenance=ticket, document="synthetic.pdf")
        self.complete(ticket)
        other = Asset.objects.create(asset_tag="CLOSE-OTHER", company=self.asset.company, category=self.asset.category)
        other_ticket = MaintenanceRecord.objects.create(asset=other, reported_by=self.user,
                            type=MaintenanceType.CORRECTIVE, description="Prueba")
        spec.asset = other
        document.maintenance = other_ticket
        ticket.asset = other
        ticket.status = MaintenanceStatus.OPEN
        for obj in (spec, document, ticket):
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ValidationError), transaction.atomic():
                    obj.delete()
                self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())


from django.test import TransactionTestCase


class ConcurrentClosureTests(TransactionTestCase):
    def test_one_close_wins_and_second_writer_cannot_rewrite_it(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        user = User.objects.create_user(username="concurrent_closure")
        company = Company.objects.create(name="Empresa", code="CONCLOSE")
        category = Category.objects.create(name="Equipo")
        asset = Asset.objects.create(asset_tag="CONCLOSE-001", company=company, category=category)
        ticket = MaintenanceRecord.objects.create(asset=asset, reported_by=user,
                    type=MaintenanceType.CORRECTIVE, description="Prueba")
        barrier = Barrier(2)

        def close(note):
            try:
                obj = MaintenanceRecord.objects.get(pk=ticket.pk)
                barrier.wait(timeout=10)
                obj.status = MaintenanceStatus.COMPLETED
                obj.resolution_notes = note
                try:
                    obj.save()
                    return "saved"
                except ValidationError:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(close, note) for note in ("Cierre A", "Cierre B")]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(results), ["denied", "saved"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, MaintenanceStatus.COMPLETED)
        self.assertEqual(ticket.history.count(), 2)
