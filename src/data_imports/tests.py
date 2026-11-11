from io import BytesIO
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.html import escape
from openpyxl import load_workbook

from accounts.models import User
from assignments.models import Assignment
from employees.models import Employee
from inventory.models import Asset, AssetGroup, AssetStatus, Brand, Category, ModelAsset
from organizations.models import Area, Company, Site

from .models import ImportStatus, StagingAsset
from .workbook import ASSETS, EMPLOYEES, ROW_FORMS, build_workbook, catalog_reference


class WorkbookImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_superuser(username="importador_sintetico")
        cls.admin_company = Company.objects.create(name="Administradora sintética", code="ACE")
        cls.owner = Company.objects.create(name="Propietaria sintética", code="SOL")
        cls.location = Site.objects.create(name="Ubicación sintética", company=cls.owner)
        cls.area = Area.objects.create(name="Área sintética", company=cls.admin_company)
        cls.category = Category.objects.create(name="Portátil sintético", group=AssetGroup.COMPUTING)
        cls.brand = Brand.objects.create(name="Marca sintética")
        cls.model = ModelAsset.objects.create(name="Modelo sintético", brand=cls.brand)

    def setUp(self):
        self.client.force_login(self.actor)
        self.list_url = reverse("admin:data_imports_stagingasset_changelist")
        self.upload_url = reverse("admin:data_imports_upload")
        self.employee_data = {
            "document_number": "0000123", "document_type": "CC", "full_name": "Persona sintética",
            "company": "ACE", "area": self.area.name,
        }
        self.asset_data = {
            "legacy_asset_tag": "0000007", "serial_number": "SERIE-7", "category": self.category.name,
            "brand": self.brand.name, "model": catalog_reference(self.model), "company": "ACE",
            "owner_company": "SOL", "property_type": "LEASED", "site": catalog_reference(self.location),
            "purchase_date": "2026-01-01", "warranty_end_date": "2027-01-01", "warranty_start": "2026-01-01",
            "supplier": "Proveedor sintético", "hostname": "equipo-sintetico", "ram": "16 GB",
            "employee_document": self.employee_data["document_number"], "initial_condition": "Funcional y sin daños.",
        }

    def workbook(self, employees=(), assets=()):
        book = load_workbook(build_workbook())
        for sheet, rows in ((EMPLOYEES, employees), (ASSETS, assets)):
            for row in rows:
                book[sheet].append([row.get(key) for key in ROW_FORMS[sheet].base_fields])
        output = BytesIO()
        book.save(output)
        return SimpleUploadedFile("inventario-sintetico.xlsx", output.getvalue())

    def upload(self, employees=(), assets=()):
        response = self.client.post(self.upload_url, {"workbook": self.workbook(employees, assets)})
        self.assertEqual(response.status_code, 302)
        return response.url

    def decide(self, row, decision):
        return self.client.post(reverse("admin:data_imports_row_decision", args=[row.pk]), {"decision": decision})

    def bulk(self, url, action, rows):
        return self.client.post(url, {"action": action, "_selected_action": [str(row.pk) for row in rows]})

    def test_upload_screen_keeps_template_link_and_accessible_file_errors(self):
        response = self.client.get(self.upload_url)
        self.assertContains(response, "itam/import-upload.css")
        self.assertContains(response, reverse("admin:data_imports_workbook"))
        self.assertContains(response, f'href="{self.list_url}">Volver a importaciones')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'accept=".xlsx"')
        self.assertContains(response, 'aria-describedby="id_workbook_helptext"')

        response = self.client.post(self.upload_url, {"workbook": SimpleUploadedFile("inventario.csv", b"placa\n001\n")})
        self.assertContains(response, "Sube un archivo .xlsx")
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_workbook_helptext id_workbook_error"')
        self.assertContains(response, 'id="id_workbook_error"')
        self.assertFalse(StagingAsset.objects.exists())

    def test_template_and_bulk_publication_with_custody_and_distinct_companies(self):
        response = self.client.get(reverse("admin:data_imports_workbook"))
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book[ASSETS]["A1"].value, "Placa")
        self.assertEqual(book[ASSETS].column_dimensions["A"].number_format, "@")
        self.assertIn("Ubicaciones", book.sheetnames)
        batch_url = self.upload([self.employee_data], [self.asset_data])
        self.assertContains(self.client.get(batch_url), "Descargar plantilla Excel")
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(Asset.objects.exists())
        rows = list(StagingAsset.objects.order_by("sheet_name"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.status for row in rows}, {ImportStatus.PENDING})
        self.assertFalse(any(row.validation_notes for row in rows))
        self.assertEqual(self.bulk(batch_url, "publish_selected", rows).status_code, 302)
        self.assertFalse(Asset.objects.exists())

        self.assertEqual(self.bulk(batch_url, "approve_selected", rows).status_code, 302)
        self.assertEqual(self.bulk(batch_url, "publish_selected", rows).status_code, 302)
        employee = Employee.objects.get()
        asset = Asset.objects.get()
        assignment = Assignment.objects.get()
        self.assertEqual(employee.document_number, "0000123")
        self.assertEqual(asset.legacy_asset_tag, "0000007")
        self.assertEqual(asset.asset_tag, "SOL-0001")
        self.assertEqual(asset.owner_company, self.owner)
        self.assertEqual(asset.company, self.admin_company)
        self.assertEqual(asset.site, self.location)
        self.assertEqual(asset.property_type, "LEASED")
        self.assertEqual(asset.status, AssetStatus.ASSIGNED)
        self.assertEqual(asset.specs.ram, "16 GB")
        self.assertEqual(asset.network.hostname, "equipo-sintetico")
        self.assertEqual(asset.warranties.get().supplier, "Proveedor sintético")
        self.assertEqual(assignment.employee, employee)
        self.assertEqual(assignment.assigned_by, self.actor)
        self.assertFalse(assignment.signed_act_pdf)
        self.assertEqual(assignment.history.first().history_user, self.actor)
        self.assertEqual(asset.history.first().history_user, self.actor)
        self.assertEqual(set(StagingAsset.objects.values_list("status", flat=True)), {ImportStatus.IMPORTED})
        self.bulk(batch_url, "publish_selected", rows)
        self.bulk(batch_url, "reject_selected", rows)
        self.assertEqual(set(StagingAsset.objects.values_list("status", flat=True)), {ImportStatus.IMPORTED})
        self.assertEqual(Assignment.objects.count(), 1)

    def test_individual_publication_requires_approved_employee_and_rolls_back_on_error(self):
        self.upload([self.employee_data], [self.asset_data])
        employee_row = StagingAsset.objects.get(sheet_name=EMPLOYEES)
        asset_row = StagingAsset.objects.get(sheet_name=ASSETS)
        detail = reverse("admin:data_imports_stagingasset_change", args=[asset_row.pk])
        self.assertContains(self.client.get(detail), "Aprobar fila")
        self.decide(asset_row, "approve")
        self.assertContains(self.client.get(detail), "Pasar a producción")
        self.decide(asset_row, "publish")
        self.assertContains(self.client.get(detail), "Publica primero la fila del custodio")
        self.assertFalse(Asset.objects.exists())
        self.decide(employee_row, "approve")
        self.decide(employee_row, "publish")

        with patch("data_imports.services.create_assignment", side_effect=ValidationError("Fallo sintético")):
            self.decide(asset_row, "publish")
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(Asset.history.exists())
        self.assertContains(self.client.get(detail), "Fallo sintético")
        self.decide(asset_row, "publish")
        self.assertEqual(Asset.objects.count(), 1)
        self.assertEqual(Assignment.objects.count(), 1)

    def test_can_correct_employee_row_and_publish_its_reviewed_values(self):
        self.upload([{**self.employee_data, "document_number": 123, "site": self.location.name}])
        row = StagingAsset.objects.get()
        edit = reverse("admin:data_imports_edit_row", args=[row.pk])
        detail = reverse("admin:data_imports_stagingasset_change", args=[row.pk])
        self.assertContains(self.client.get(detail), "Editar datos")
        self.assertContains(self.client.get(edit), 'value="123"')
        response = self.client.post(edit, {**self.employee_data, "full_name": "", "version": row.updated_at.isoformat()})
        self.assertContains(response, 'id="id_full_name_error"')
        row.refresh_from_db()
        self.assertEqual(row.workbook_data["document_number"], 123)

        response = self.client.post(edit, {
            **self.employee_data, "site": self.location.name, "version": row.updated_at.isoformat(),
        })
        self.assertRedirects(response, detail)
        row.refresh_from_db()
        self.assertEqual(row.employee_document, "0000123")
        self.assertFalse(row.validation_notes)
        self.assertEqual(row.history.first().history_user, self.actor)
        self.assertFalse(Employee.objects.exists())
        self.decide(row, "approve")
        self.decide(row, "publish")
        employee = Employee.objects.get()
        self.assertEqual(employee.document_number, "0000123")
        self.assertEqual(employee.company, self.admin_company)
        self.assertEqual(employee.site, self.location)
        self.assertNotContains(self.client.get(detail), "Editar datos")
        self.assertEqual(self.client.post(edit, self.employee_data).status_code, 403)

    def test_editing_approved_asset_requires_a_new_decision_and_keeps_dates(self):
        self.upload([self.employee_data], [self.asset_data])
        employee = StagingAsset.objects.get(sheet_name=EMPLOYEES)
        row = StagingAsset.objects.get(sheet_name=ASSETS)
        self.decide(employee, "approve")
        self.decide(employee, "publish")
        self.decide(row, "approve")
        row.refresh_from_db()
        version = row.updated_at.isoformat()
        edit = reverse("admin:data_imports_edit_row", args=[row.pk])
        decision = reverse("admin:data_imports_row_decision", args=[row.pk])
        self.assertContains(self.client.get(edit), '<option value="" selected>Sin indicar</option>', html=True)
        self.assertContains(self.client.get(edit), 'value="2026-01-01"')
        self.assertEqual(self.client.post(edit, {**self.asset_data, "version": version}).status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.status, ImportStatus.APPROVED)
        self.assertEqual(row.updated_at.isoformat(), version)

        changes = {**self.asset_data, "legacy_asset_tag": "0000099", "observations": "Observación corregida"}
        self.assertEqual(self.client.post(edit, {**changes, "version": version}).status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.status, ImportStatus.PENDING)
        self.assertEqual(row.legacy_asset_tag, "0000099")
        self.assertEqual(row.workbook_data["purchase_date"], "2026-01-01")
        self.assertFalse(row.validation_notes)
        self.assertContains(self.client.post(edit, {**changes, "version": version}), "La fila cambió durante la edición")
        self.client.post(decision, {"decision": "approve", "version": version})
        row.refresh_from_db()
        self.assertEqual(row.status, ImportStatus.PENDING)
        self.decide(row, "publish")
        self.assertFalse(Asset.objects.exists())
        self.decide(row, "approve")
        self.decide(row, "publish")
        self.assertEqual(Asset.objects.get().legacy_asset_tag, "0000099")
        self.assertEqual(Asset.objects.get().observations, "Observación corregida")

    def test_review_edit_and_decision_preserve_the_list_query(self):
        self.upload([self.employee_data, *(
            {**self.employee_data, "document_number": f"0000{number}", "full_name": f"Persona sintética {number}"}
            for number in (2, 3)
        )])
        row = StagingAsset.objects.get(employee_document=self.employee_data["document_number"])
        filters = urlencode({"batch_id__exact": row.batch_id, "status__exact": row.status,
                             "q": "Persona sintética", "o": "1", "p": "1"})
        preserved = urlencode({"_changelist_filters": filters})
        listing = f"{self.list_url}?{filters}"
        detail = f"{reverse('admin:data_imports_stagingasset_change', args=[row.pk])}?{preserved}"
        edit = f"{reverse('admin:data_imports_edit_row', args=[row.pk])}?{preserved}"
        decision = f"{reverse('admin:data_imports_row_decision', args=[row.pk])}?{preserved}"
        self.assertContains(self.client.get(listing), f'href="{escape(detail)}"')
        page = self.client.get(detail)
        self.assertContains(page, f'href="{escape(listing)}">Volver a importaciones')
        self.assertContains(page, f'href="{escape(edit)}">Editar datos')
        self.assertContains(self.client.get(edit), f'href="{escape(detail)}">Volver a la fila')
        response = self.client.post(edit, {**self.employee_data, "phone": "0001", "version": row.updated_at.isoformat()})
        self.assertRedirects(response, detail)
        row.refresh_from_db()
        self.assertRedirects(self.client.post(decision, {"decision": "approve", "version": row.updated_at.isoformat()}), detail)
        self.assertContains(self.client.get(detail), f'href="{escape(listing)}">Volver a importaciones')
        without_page = listing.rsplit("&p=", 1)[0]
        with patch.object(admin.site.get_model_admin(StagingAsset), "list_per_page", 1):
            self.assertRedirects(self.client.get(f"{without_page}&p=99"), without_page)

    def test_validation_blocks_retired_custody_duplicates_and_missing_condition(self):
        invalid_asset = {**self.asset_data, "initial_condition": ""}
        second_asset = {**self.asset_data, "legacy_asset_tag": "08", "serial_number": "SERIE-8"}
        third_asset = {**second_asset, "employee_document": "", "initial_condition": ""}
        self.upload([{**self.employee_data, "status": "RETIRO"}], [invalid_asset, second_asset, third_asset])
        rows = list(StagingAsset.objects.filter(sheet_name=ASSETS).order_by("row_number"))
        self.assertIn("Condición de entrega", rows[0].validation_notes)
        self.assertIn("Placa repetida", rows[1].validation_notes)
        self.decide(rows[2], "reject")
        self.decide(rows[1], "approve")
        rows[1].refresh_from_db()
        self.assertEqual(rows[1].status, ImportStatus.PENDING)
        self.assertIn("empleado retirado", rows[1].validation_notes)

    def test_reference_prevents_duplicate_asset_without_plate_or_serial_across_uploads(self):
        asset = {**self.asset_data, "legacy_asset_tag": "", "serial_number": "", "import_reference": "Equipo-01",
                 "employee_document": "", "initial_condition": ""}
        self.upload(assets=[asset])
        row = StagingAsset.objects.get()
        self.decide(row, "approve")
        self.decide(row, "publish")
        self.upload(assets=[{**asset, "import_reference": "EQUIPO-01"}])
        retry = StagingAsset.objects.exclude(pk=row.pk).get()
        self.assertIn("Referencia de carga ya publicada", retry.validation_notes)
        self.assertEqual(Asset.objects.count(), 1)

    def test_permission_and_csrf_checks_cover_review_upload_and_publish(self):
        self.upload([self.employee_data])
        row = StagingAsset.objects.get()
        decision = reverse("admin:data_imports_row_decision", args=[row.pk])
        edit = reverse("admin:data_imports_edit_row", args=[row.pk])
        self.assertEqual(self.client.get(decision).status_code, 405)
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.actor)
        self.assertEqual(secure_client.post(decision, {"decision": "approve"}).status_code, 403)
        self.assertEqual(secure_client.post(edit, self.employee_data).status_code, 403)
        viewer = User.objects.create_user(username="consulta_sintetica", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename="view_stagingasset"))
        self.client.force_login(viewer)
        self.assertNotContains(self.client.get(self.list_url), "Cargar Excel")
        self.assertEqual(self.client.get(self.upload_url).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:data_imports_workbook")).status_code, 403)
        self.assertEqual(self.client.post(decision, {"decision": "approve"}).status_code, 403)
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.post(edit, self.employee_data).status_code, 403)
        viewer.user_permissions.add(Permission.objects.get(codename="change_stagingasset"))
        self.assertEqual(self.client.post(decision, {"decision": "approve"}).status_code, 302)
        self.assertEqual(self.client.post(decision, {"decision": "publish"}).status_code, 403)
        self.bulk(self.list_url, "publish_selected", [row])
        self.assertFalse(Employee.objects.exists())

    def test_rejects_formulas_and_detects_numeric_document(self):
        response = self.client.post(self.upload_url, {
            "workbook": self.workbook(employees=[{**self.employee_data, "full_name": "=1+1"}]),
        })
        self.assertContains(response, "fila 2")
        self.assertFalse(StagingAsset.objects.exists())
        self.upload([{**self.employee_data, "document_number": 123}])
        self.assertIn("formato Texto", StagingAsset.objects.get().validation_notes)
