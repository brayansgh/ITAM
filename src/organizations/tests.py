from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.forms import modelform_factory
from accounts.models import User
from assignments.models import Assignment, AssignmentStatus
from assignments.services import create_assignment, return_assignment
from employees.models import Employee, EmployeeStatus
from inventory.models import Asset, Category, AssetStatus
from .models import Company, Site, Area


class OrganizationIntegrityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Empresa A", code="A")
        self.other = Company.objects.create(name="Empresa B", code="B")
        self.site = Site.objects.create(company=self.company, name="Sede A")
        self.area = Area.objects.create(company=self.company, name="Área A")
        self.foreign_site = Site.objects.create(company=self.other, name="Sede B")
        self.foreign_area = Area.objects.create(company=self.other, name="Área B")
        self.category = Category.objects.create(name="Categoría")
        self.user = User.objects.create_user(username="integrity_operator")
        self.employee = Employee.objects.create(company=self.company, site=self.site, area=self.area, full_name="Persona sintética")
        self.asset = Asset.objects.create(company=self.company, owner_company=self.other, site=self.site, category=self.category, asset_tag="ORG-001")

    def assign(self):
        return create_assignment(asset_id=self.asset.pk, employee_id=self.employee.pk,
                                 assigned_by=self.user, initial_condition="Buen estado")

    def test_retired_recipient_is_rejected_without_mutations(self):
        self.employee.status = EmployeeStatus.RETIRO
        self.employee.save()
        before = self.asset.history.count()
        with self.assertRaises(ValidationError):
            self.assign()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.AVAILABLE)
        self.assertEqual(self.asset.history.count(), before)
        self.assertFalse(Assignment.objects.exists())

    def test_direct_assignment_cannot_bypass_retired_recipient_rule(self):
        self.employee.status = EmployeeStatus.RETIRO
        self.employee.save()
        with self.assertRaises(ValidationError):
            Assignment.objects.create(asset=self.asset, employee=self.employee, assigned_by=self.user,
                                      initial_condition="Buen estado")
        self.assertFalse(Assignment.objects.exists())
        self.assertFalse(Assignment.history.exists())

    def test_return_and_pdf_updates_remain_allowed_after_retirement(self):
        assignment = self.assign()
        self.employee.status = EmployeeStatus.RETIRO
        self.employee.save()
        assignment.observations = "Recepción pendiente"
        assignment.save(update_fields=["observations"])
        return_assignment(assignment_id=assignment.pk, condition="Recibido", returned_by=self.user)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.RETURNED)
        with self.assertRaises(ValidationError):
            assignment.status = AssignmentStatus.ACTIVE
            assignment.save()

    def test_employee_can_share_a_site_and_must_use_an_area_of_its_company(self):
        self.employee.site = self.foreign_site
        self.employee.full_clean()
        self.employee.save(update_fields=["site"])
        self.employee.area = self.foreign_area
        with self.assertRaises(ValidationError):
            self.employee.full_clean()
        with self.assertRaises(ValidationError):
            self.employee.save()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.site, self.foreign_site)
        self.assertEqual(self.employee.area, self.area)

    def test_asset_shared_site_is_allowed_in_model_and_form(self):
        self.asset.site = self.foreign_site
        self.asset.full_clean()
        self.asset.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site, self.foreign_site)
        self.assertEqual(self.asset.company, self.company)
        form_type = modelform_factory(Asset, fields=["company", "site", "category", "asset_tag"])
        form = form_type(data={"company": self.company.pk, "site": self.foreign_site.pk,
                               "category": self.category.pk, "asset_tag": "ORG-NEW"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_area_company_change_cannot_invalidate_existing_links(self):
        self.area.company = self.other
        with self.assertRaises(ValidationError):
            self.area.full_clean()
        with self.assertRaises(ValidationError):
            self.area.save()
        self.area.refresh_from_db()
        self.assertEqual(self.area.company, self.company)

    def test_unused_site_and_area_can_move_company(self):
        for obj in (self.foreign_site, self.foreign_area):
            obj.company = self.company
            obj.save()
            obj.refresh_from_db()
            self.assertEqual(obj.company, self.company)

    def test_owner_company_and_borrower_can_differ_from_asset_manager(self):
        self.assertEqual(self.asset.owner_company, self.other)
        borrower = Employee.objects.create(company=self.other, full_name="Persona de otra compañía")
        assignment = create_assignment(asset_id=self.asset.pk, employee_id=borrower.pk,
                                       assigned_by=self.user, initial_condition="Buen estado")
        self.assertEqual(assignment.employee, borrower)

    def test_partial_update_uses_persisted_unchanged_company(self):
        self.asset.company = self.other  # No se incluye en update_fields.
        self.asset.site = self.site
        self.asset.save(update_fields=["site"])
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.company, self.company)
        self.asset.company = self.other
        self.asset.save(update_fields=["company"])
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.company, self.other)
        self.assertEqual(self.asset.site, self.site)

    def test_valid_company_site_area_transfer_can_be_saved_together(self):
        self.employee.company = self.other
        self.employee.site = self.foreign_site
        self.employee.area = self.foreign_area
        self.employee.save()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.company, self.other)
        self.assertEqual(self.employee.site, self.foreign_site)

    def test_site_can_change_legacy_company_with_existing_references(self):
        self.site.company = self.other
        self.site.full_clean()
        self.site.save()
        self.employee.refresh_from_db()
        self.employee.full_clean()
        self.assertEqual(self.employee.site, self.site)
        self.assertEqual(self.employee.company, self.company)
        self.asset.refresh_from_db()
        self.asset.full_clean()
        self.assertEqual(self.asset.site, self.site)
        self.assertEqual(self.asset.company, self.company)

    def test_cleanup_keeps_same_named_sites_and_areas_of_different_companies(self):
        from io import StringIO
        from django.core.management import call_command
        first = Site.objects.create(company=self.company, name="Principal")
        second = Site.objects.create(company=self.other, name="Principal")
        first_area = Area.objects.create(company=self.company, name="General")
        second_area = Area.objects.create(company=self.other, name="General")
        call_command("clean_organizations", stdout=StringIO())
        self.assertTrue(Site.objects.filter(pk=first.pk).exists())
        self.assertTrue(Site.objects.filter(pk=second.pk).exists())
        self.assertTrue(Area.objects.filter(pk=first_area.pk).exists())
        self.assertTrue(Area.objects.filter(pk=second_area.pk).exists())

    def test_bulk_cleanup_cannot_move_asset_to_another_company_site(self):
        from data_imports.management.commands.clean_organizations import Command
        from django.db import transaction
        with self.assertRaises(ValidationError), transaction.atomic():
            Command().move_relation(Asset.objects.filter(pk=self.asset.pk), "site", self.foreign_site)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site, self.site)

    def test_shared_site_allows_real_admin_transition_to_maintenance(self):
        from django.urls import reverse
        from maintenance.models import MaintenanceRecord
        self.asset.site = self.foreign_site
        self.asset.save()
        operator = User.objects.create_superuser(username="shared_site_operator", password="Test-4826!")
        self.client.force_login(operator)
        data = {
            "asset_tag": self.asset.asset_tag, "legacy_asset_tag":"", "serial_number":"",
            "category":str(self.category.pk), "company":str(self.company.pk),
            "owner_company":str(self.other.pk), "site":str(self.foreign_site.pk),
            "status":AssetStatus.IN_MAINTENANCE, "property_type":"OWNED", "_save":"Guardar",
        }
        for prefix in ("specs", "network", "warranties"):
            data.update({prefix+"-TOTAL_FORMS":"0", prefix+"-INITIAL_FORMS":"0",
                         prefix+"-MIN_NUM_FORMS":"0", prefix+"-MAX_NUM_FORMS":"1000"})
        response = self.client.post(reverse("admin:inventory_asset_change", args=[self.asset.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.IN_MAINTENANCE)
        self.assertEqual(self.asset.company, self.company)
        self.assertEqual(self.asset.owner_company, self.other)
        self.assertEqual(self.asset.site, self.foreign_site)
        self.assertEqual(MaintenanceRecord.objects.filter(asset=self.asset).count(), 1)
        self.assertEqual(self.asset.history.first().history_user, operator)

    def test_shared_site_survives_assignment_maintenance_return_and_closure(self):
        from maintenance.models import MaintenanceRecord, MaintenanceType, MaintenanceStatus
        self.asset.site = self.foreign_site
        self.asset.save()
        assignment = self.assign()
        ticket = MaintenanceRecord.objects.create(asset=self.asset, reported_by=self.user,
                    type=MaintenanceType.CORRECTIVE, description="Prueba")
        return_assignment(assignment_id=assignment.pk, condition="Recibido", returned_by=self.user)
        ticket.status = MaintenanceStatus.COMPLETED
        ticket.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, AssetStatus.AVAILABLE)
        self.assertEqual(self.asset.site, self.foreign_site)
        self.assertEqual(self.asset.company, self.company)

    def test_cleanup_keeps_shared_assets_when_merging_same_owner_sites(self):
        from django.db import transaction
        from data_imports.management.commands.clean_organizations import Command
        self.asset.site = self.foreign_site
        self.asset.save()
        target = Site.objects.create(company=self.other, name="Destino de la misma compañía propietaria de la sede")
        with transaction.atomic():
            Command().move_relation(Asset.objects.filter(pk=self.asset.pk), "site", target)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site, target)
        self.assertEqual(self.asset.company, self.company)

    def test_location_metadata_edits_do_not_revalidate_unchanged_legacy_company(self):
        from django.urls import reverse
        # Solo la base temporal: reproducir una ubicación antigua compartida.
        Employee.objects.filter(pk=self.employee.pk).update(company=self.other)
        operator=User.objects.create_superuser(username="location_editor",password="Test-4826!")
        self.client.force_login(operator)
        response=self.client.post(reverse("admin:organizations_site_change",args=[self.site.pk]),{
            "name":"Ubicación actualizada", "address":"Dirección sintética", "city":"Ciudad sintética", "status":"ACTIVE", "_save":"Guardar",
        })
        self.assertEqual(response.status_code,302)
        self.site.refresh_from_db()
        self.assertEqual(self.site.name,"Ubicación actualizada")
        self.assertEqual(self.site.company_id,self.company.pk)


class CompanyAdminTests(TestCase):
    def test_company_change_confirmation_uses_feminine_article(self):
        self.client.force_login(User.objects.create_superuser(username="company_operator"))
        company = Company.objects.create(name="Compañía inicial", code="TEST")
        change_url = reverse("admin:organizations_company_change", args=[company.pk])

        response = self.client.post(change_url, {
            "name": "Compañía <editada>",
            "code": company.code,
            "status": company.status,
            "_save": "Guardar",
        }, follow=True)

        self.assertRedirects(response, reverse("admin:organizations_company_changelist"))
        self.assertContains(
            response,
            f'La compañía “<a href="{change_url}">Compañía &lt;editada&gt;</a>” se cambió correctamente.',
        )
        company.refresh_from_db()
        self.assertEqual(company.name, "Compañía <editada>")
