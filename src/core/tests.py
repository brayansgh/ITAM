import tempfile
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from assignments.models import Assignment, AssignmentStatus, OffboardingRecord, OffboardingRecordItem
from assignments.services import create_assignment, return_assignment
from data_imports.admin import set_import_status
from data_imports.models import ImportStatus, StagingAsset
from employees.models import Employee
from inventory.models import Asset, AssetNetwork, AssetSpecs, AssetStatus, AssetWarranty, Brand, Category, ModelAsset
from maintenance.models import MaintenanceDocument, MaintenanceRecord, MaintenanceType
from organizations.models import Area, Company, Site
from .admin_audit import StandardHistoryAdmin
from .audit import format_value, version_row


class CrossModuleAuditTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.actor = User.objects.create_superuser(username="audit_operator", password="Audit-test-4826!")
        self.client.force_login(self.actor)
        self.company = Company.objects.create(name="Empresa auditada", code="AUD")
        self.category = Category.objects.create(name="Categoría auditada")
        self.asset = Asset.objects.create(asset_tag="AUD-001", company=self.company, category=self.category)
        self.employee = Employee.objects.create(full_name="Persona de prueba", company=self.company)

    def history(self, obj):
        return self.client.get(reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_history", args=[obj.pk]))

    def test_every_domain_model_has_history(self):
        models = [User, Group, Company, Site, Area, Category, Brand, ModelAsset, Asset,
                  AssetSpecs, AssetNetwork, AssetWarranty, Employee, Assignment,
                  OffboardingRecord, OffboardingRecordItem, MaintenanceRecord,
                  MaintenanceDocument, StagingAsset]
        for model in models:
            with self.subTest(model=model._meta.label):
                self.assertTrue(hasattr(model, "history"))
                if admin.site.is_registered(model):
                    self.assertIsInstance(admin.site._registry[model], StandardHistoryAdmin)

    def test_standard_history_is_available_across_modules(self):
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                       assigned_by=self.actor, initial_condition="Buen estado")
        maintenance = MaintenanceRecord.objects.create(
            asset=self.asset, reported_by=self.actor, type=MaintenanceType.PREVENTIVE, description="Prueba",
        )
        record = OffboardingRecord.objects.create(employee=self.employee, received_by=self.actor)
        staging = StagingAsset.objects.create(sheet_name="Prueba", row_number=1)
        group = Group.objects.create(name="Auditoría")
        site = Site.objects.create(company=self.company, name="Sede auditada")
        area = Area.objects.create(company=self.company, name="Área auditada")
        brand = Brand.objects.create(name="Marca auditada")
        model = ModelAsset.objects.create(name="Modelo auditado", brand=brand)
        for obj in [self.actor, self.company, self.category, self.asset, self.employee,
                    maintenance, assignment, record, staging, group, site, area, brand, model]:
            with self.subTest(model=obj._meta.label):
                response = self.history(obj)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "admin/core/audit_history.html")
                self.assertContains(response, "Historial de datos")
                self.assertContains(response, "Eventos administrativos")
                self.assertEqual(response.context["audit_counts"]["total"], obj.history.count())

    def test_history_layout_keeps_values_escaped_and_sections_separate(self):
        self.category.description = '<script>alert("audit")</script>'
        self.category.save()
        AssetSpecs.objects.create(asset=self.asset, ram="8 GB")
        response = self.history(self.category)
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert("audit")</script>')
        self.assertContains(response, 'id="audit-data"')
        self.assertContains(response, 'id="audit-events"')
        self.assertContains(response, 'Versiones de datos')
        self.assertContains(response, 'solo lectura')
        self.assertContains(response, 'itam-audit-old')
        self.assertContains(response, 'itam-audit-new')
        self.assertContains(response, 'No se suman ambos conteos')
        self.assertContains(response, 'Sin responsable registrado')
        from django.utils import timezone
        offset = timezone.localtime(self.category.history.first().history_date).strftime('%Z')
        self.assertContains(response, offset)
        self.assertContains(self.history(self.asset), 'id="audit-related"')

    def test_profile_admin_records_actor_and_exactly_one_admin_event(self):
        self.actor.first_name = "Lucía"
        self.actor.last_name = "García"
        self.actor.save(update_fields=["first_name", "last_name"])
        url = reverse("admin:inventory_category_change", args=[self.category.pk])
        response = self.client.post(url, {"name": "Categoría nueva", "description": "Actualizada"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.category.history.first().history_user, self.actor)
        response = self.history(self.category)
        self.assertEqual(response.context["audit_counts"], {"total": 2, "created": 1, "modified": 1, "deleted": 0})
        self.assertEqual(response.context["admin_events"].paginator.count, 1)
        self.assertContains(response, "Categoría auditada")
        self.assertContains(response, "Categoría nueva")
        self.assertEqual(response.context["audit_rows"][0]["actor"], "Lucía García")
        self.assertContains(response, "<td>Lucía García</td>", html=True)
        self.assertNotContains(response, "<td>audit_operator</td>", html=True)

    def test_asset_admin_does_not_double_log(self):
        request = RequestFactory().post("/")
        request.user = self.actor
        model_admin = admin.site._registry[Asset]
        self.asset.observations = "Cambio de prueba"
        form = Mock(changed_data=["observations"])
        model_admin.save_model(request, self.asset, form, True)
        model_admin.log_change(request, self.asset, [{"changed": {"fields": ["Observaciones"]}}])
        self.assertEqual(LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(Asset), object_id=str(self.asset.pk),
        ).count(), 1)
        self.assertEqual(self.asset.history.first().history_user, self.actor)

    def test_assignment_and_return_services_capture_actor_and_state(self):
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                       assigned_by=self.actor, initial_condition="Buen estado")
        self.assertEqual(assignment.history.first().history_user, self.actor)
        self.assertEqual(self.asset.history.first().history_user, self.actor)
        return_assignment(assignment_id=assignment.pk, condition="Recibido", returned_by=self.actor)
        latest = assignment.history.first()
        self.assertEqual(latest.history_user, self.actor)
        self.assertEqual(latest.status, AssignmentStatus.RETURNED)
        response = self.history(assignment)
        self.assertContains(response, "Vigente / En Custodia")
        self.assertContains(response, "Devuelto")

    def test_transaction_rollback_removes_audit_rows(self):
        count = self.asset.history.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.asset.status = AssetStatus.LOST
                self.asset.save()
                raise RuntimeError("Revertir prueba")
        self.assertEqual(self.asset.history.count(), count)

    def test_import_actions_capture_actor_and_skip_unchanged_rows(self):
        item = StagingAsset.objects.create(sheet_name="Prueba", row_number=1)
        qs = StagingAsset.objects.filter(pk=item.pk)
        set_import_status(qs, ImportStatus.APPROVED, self.actor)
        set_import_status(qs, ImportStatus.APPROVED, self.actor)
        self.assertEqual(item.history.count(), 2)
        self.assertEqual(item.history.first().history_user, self.actor)
        self.assertContains(self.history(item), "Aprobado para Importar")

    def test_m2m_changes_outside_admin_also_have_versions(self):
        group = Group.objects.create(name="Grupo auditable")
        permission = Permission.objects.get(content_type__app_label="inventory", codename="view_asset")
        group.permissions.add(permission)
        latest = group.history.first()
        changes = version_row(latest, latest.prev_record)["changes"]
        self.assertEqual(changes[0]["field"], "Permisos")
        self.assertIn(str(permission), changes[0]["new"])
        self.actor.groups.add(group)
        latest = self.actor.history.first()
        changes = version_row(latest, latest.prev_record)["changes"]
        self.assertEqual(changes[0]["field"], "Grupos")
        self.assertIn("Grupo auditable", changes[0]["new"])

    def test_inline_changes_are_visible_on_parent(self):
        specs = AssetSpecs.objects.create(asset=self.asset, ram="8 GB")
        specs.ram = "16 GB"
        specs.save()
        response = self.history(self.asset)
        self.assertEqual(response.context["related_count"], 2)
        self.assertContains(response, "8 GB")
        self.assertContains(response, "16 GB")

    def test_document_history_never_displays_private_paths(self):
        maintenance = MaintenanceRecord.objects.create(
            asset=self.asset, reported_by=self.actor, type=MaintenanceType.PREVENTIVE, description="Prueba",
        )
        document = MaintenanceDocument.objects.create(
            maintenance=maintenance, document=ContentFile(b"%PDF-1.4 synthetic", name="synthetic.pdf"),
        )
        document.document.save("second.pdf", ContentFile(b"%PDF-1.4 synthetic"))
        response = self.history(maintenance)
        self.assertContains(response, "Archivo adjunto")
        self.assertNotContains(response, "maintenance_docs/")
        self.assertNotContains(response, "/media/")

    def test_deleted_record_history_is_preserved(self):
        site = Site.objects.create(company=self.company, name="Sede temporal")
        url = reverse("admin:organizations_site_history", args=[site.pk])
        site.delete()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["audit_counts"]["deleted"], 1)

    def test_missing_actor_is_not_falsely_attributed_to_system(self):
        self.assertContains(self.history(self.company), "Sin responsable registrado")

    def test_history_permissions_are_enforced_across_modules(self):
        viewer = User.objects.create_user(username="restricted_auditor", is_staff=True)
        self.client.force_login(viewer)
        for obj in [self.company, self.asset, self.employee]:
            self.assertEqual(self.history(obj).status_code, 403)
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="organizations", codename="view_company",
        ))
        self.assertEqual(self.history(self.company).status_code, 200)
        self.assertEqual(self.history(self.asset).status_code, 403)

    def test_raw_history_restore_endpoint_is_denied(self):
        record = self.asset.history.first()
        url = reverse("admin:inventory_asset_simple_history", args=[self.asset.pk, record.history_id])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"status": AssetStatus.LOST}).status_code, 403)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.AVAILABLE)

    def test_paginated_history_counts_all_versions_without_admin_double_count(self):
        for i in range(52):
            self.category.description = f"Cambio {i}"
            self.category.save()
        response = self.history(self.category)
        self.assertEqual(response.context["audit_counts"]["total"], 53)
        self.assertEqual(len(response.context["audit_rows"]), 50)
        response = self.client.get(reverse("admin:inventory_category_history", args=[self.category.pk]), {"page": 2})
        self.assertEqual(len(response.context["audit_rows"]), 3)
        self.assertEqual(response.context["audit_counts"]["total"], 53)

    def test_first_modification_does_not_invent_a_previous_state(self):
        self.company.history.all().delete()  # Solo la base temporal de esta prueba.
        self.company.name = "Nombre nuevo"
        self.company.save()
        response = self.history(self.company)
        self.assertContains(response, "Sin versión anterior disponible")
        self.assertEqual(response.context["audit_counts"]["created"], 0)

    def test_formatting_is_consistent(self):
        self.assertEqual(format_value(None, None), "Sin dato")
        self.assertEqual(format_value(None, True), "Sí")
        self.assertEqual(format_value(None, date(2026, 11, 6)), "06/11/2026")
        with override_settings(LANGUAGE_CODE="es-co"):
            self.assertEqual(format_value(None, Decimal("12.50")), "12,50")

    def test_html_values_are_escaped(self):
        self.category.description = '<script>alert("audit")</script>'
        self.category.save()
        response = self.history(self.category)
        self.assertNotContains(response, '<script>alert("audit")</script>')
        self.assertContains(response, "&lt;script&gt;")

    def test_maintenance_sync_uses_actual_actor_not_reporter(self):
        reporter = User.objects.create_user(username="ticket_reporter")
        ticket = MaintenanceRecord(
            asset=self.asset, reported_by=reporter, type=MaintenanceType.CORRECTIVE,
            description="Prueba de responsable",
        )
        ticket._history_user = self.actor
        ticket.save()
        self.assertEqual(self.asset.history.first().history_user, self.actor)
        self.assertEqual(ticket.history.first().history_user, self.actor)

    def test_automated_ticket_does_not_invent_an_auditor(self):
        self.asset.status = AssetStatus.IN_MAINTENANCE
        self.asset.save()
        ticket = MaintenanceRecord.objects.get(asset=self.asset)
        self.assertIsNone(ticket.history.first().history_user)

    def test_maintenance_preserves_custody_and_records_actor(self):
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                       assigned_by=self.actor, initial_condition="Buen estado")
        self.asset.refresh_from_db()
        self.asset.status = AssetStatus.IN_MAINTENANCE
        self.asset._history_user = self.actor
        self.asset.save()
        self.assertEqual(assignment.history.first().history_user, self.actor)
        self.assertEqual(assignment.history.first().status, AssignmentStatus.ACTIVE)
        self.assertEqual(self.asset.history.first().history_user, self.actor)

    def test_bulk_organization_reassignment_is_audited_without_status_signals(self):
        from data_imports.management.commands.clean_organizations import Command
        site = Site.objects.create(company=self.company, name="Sede destino")
        with transaction.atomic():
            Command().move_relation(Asset.objects.filter(pk=self.asset.pk), "site", site)
        self.assertEqual(self.asset.history.first().site_id, site.pk)
        self.assertEqual(self.asset.history.count(), 2)
        self.assertFalse(MaintenanceRecord.objects.filter(asset=self.asset).exists())

    def test_import_command_can_load_current_model_names(self):
        from data_imports.management.commands.process_approved import Command
        self.assertTrue(callable(Command().handle))

    def test_preexisting_m2m_relations_are_not_presented_as_new_grants(self):
        from datetime import timedelta
        from django.db.migrations.recorder import MigrationRecorder
        cutoff = MigrationRecorder.Migration.objects.get(
            app="inventory", name="0007_estandarizar_auditoria",
        ).applied
        user = User.objects.create_user(username="old_account")
        old = user.history.first()
        user.history.filter(history_id=old.history_id).update(history_date=cutoff - timedelta(days=1))
        group = Group.objects.create(name="Grupo preexistente")
        user.groups.add(group)
        response = self.history(user)
        latest_row = response.context["audit_rows"][0]
        self.assertEqual(latest_row["changes"], [])
        self.assertContains(response, "no se reconstruyen diferencias de esas relaciones")

    def test_audit_health_report_has_explicit_counts_without_personal_data(self):
        import json
        from io import StringIO
        from django.core.management import call_command
        output = StringIO()
        call_command("audit_status", "--json", "--fail-on-missing", stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report["missing_models"], [])
        asset = next(item for item in report["models"] if item["model"] == "inventory.Asset")
        self.assertEqual(asset["current_records"], 1)
        self.assertEqual(asset["versions"], 1)
        self.assertEqual(asset["current_records_with_versions"], 1)
        self.assertNotIn(self.actor.username, output.getvalue())
        self.assertNotIn(self.asset.asset_tag, output.getvalue())

    def test_proxy_histories_use_the_concrete_models_history(self):
        from employees.models import EmployeeStatus, RetiredEmployee
        from inventory.models import DecommissionedAsset
        from assignments.models import EmployeeAssetSummary
        self.employee.status = EmployeeStatus.RETIRO
        self.employee.save()
        from core.testing import complete_decommission
        complete_decommission(self.asset)
        for model, object_id in [
            (DecommissionedAsset, self.asset.pk),
            (EmployeeAssetSummary, self.employee.pk),
            (RetiredEmployee, self.employee.pk),
        ]:
            with self.subTest(model=model._meta.label):
                url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_history", args=[object_id])
                response = self.client.get(url, follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "admin/core/audit_history.html")


class AdminValidationRollbackTests(TestCase):
    def test_late_validation_rolls_back_and_shows_error_instead_of_500(self):
        from unittest.mock import patch
        from django.core.exceptions import ValidationError
        user=User.objects.create_superuser(username="validation_operator",password="Test-4826!")
        category=Category.objects.create(name="Nombre previo")
        self.client.force_login(user)
        model_admin=admin.site._registry[Category]
        before=category.history.count()
        with patch.object(model_admin,"save_related",side_effect=ValidationError("Conflicto de validación sintético")):
            response=self.client.post(reverse("admin:inventory_category_change",args=[category.pk]),
                    {"name":"Cambio que debe revertirse","description":"Prueba","_save":"Guardar"},follow=True)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"No se guardaron los cambios")
        self.assertContains(response,"Conflicto de validación sintético")
        category.refresh_from_db()
        self.assertEqual(category.name,"Nombre previo")
        self.assertEqual(category.history.count(),before)
