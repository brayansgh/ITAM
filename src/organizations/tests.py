from django.core.exceptions import ValidationError
from django.test import TestCase
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
        self.asset = Asset.objects.create(company=self.company, site=self.site, category=self.category, asset_tag="ORG-001")

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

    def test_employee_wrong_site_or_area_is_rejected(self):
        for field, value in [("site", self.foreign_site), ("area", self.foreign_area)]:
            with self.subTest(field=field):
                self.employee.refresh_from_db()
                setattr(self.employee, field, value)
                with self.assertRaises(ValidationError): self.employee.full_clean()
                with self.assertRaises(ValidationError): self.employee.save()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.site, self.site)
        self.assertEqual(self.employee.area, self.area)

    def test_asset_wrong_site_is_rejected_in_model_and_form(self):
        self.asset.site = self.foreign_site
        with self.assertRaises(ValidationError): self.asset.full_clean()
        with self.assertRaises(ValidationError): self.asset.save()
        form_type = modelform_factory(Asset, fields=["company", "site", "category", "asset_tag"])
        form = form_type(data={"company": self.company.pk, "site": self.foreign_site.pk,
                               "category": self.category.pk, "asset_tag": "ORG-NEW"})
        self.assertFalse(form.is_valid())
        self.assertIn("site", form.errors)

    def test_parent_company_change_cannot_invalidate_existing_links(self):
        for obj in (self.site, self.area):
            with self.subTest(model=type(obj).__name__):
                obj.company = self.other
                with self.assertRaises(ValidationError): obj.full_clean()
                with self.assertRaises(ValidationError): obj.save()
                obj.refresh_from_db()
                self.assertEqual(obj.company, self.company)

    def test_unused_site_and_area_can_move_company(self):
        for obj in (self.foreign_site, self.foreign_area):
            obj.company = self.company
            obj.save()
            obj.refresh_from_db()
            self.assertEqual(obj.company, self.company)

    def test_owner_company_and_borrower_can_differ_from_asset_manager(self):
        self.asset.owner_company = self.other
        self.asset.save()
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
        with self.assertRaises(ValidationError): self.asset.save(update_fields=["company"])

    def test_valid_company_site_area_transfer_can_be_saved_together(self):
        self.employee.company = self.other
        self.employee.site = self.foreign_site
        self.employee.area = self.foreign_area
        self.employee.save()
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.company, self.other)
        self.assertEqual(self.employee.site, self.foreign_site)

    def test_site_guard_also_applies_when_only_assets_reference_it(self):
        self.employee.site = None
        self.employee.save()
        self.site.company = self.other
        with self.assertRaises(ValidationError): self.site.save()

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
