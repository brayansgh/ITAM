import tempfile
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from organizations.models import Company
from inventory.models import Asset, AssetStatus, Category
from employees.models import Employee
from assignments.models import Assignment, AssignmentStatus
from assignments.services import create_assignment, return_assignment
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from accounts.models import Role
from assignments.admin import AssignmentAdmin
from django.urls import reverse
from django.core.files.base import ContentFile
from django.test import override_settings


class ReturnAssignmentTests(TestCase):

    def setUp(self):
        """
        Prepara los registros necesarios para cada prueba.
        """

        # Usuario de tecnología que entrega y recibe activos.
        self.user = User.objects.create_user(
            username="test_tecnico",
            password="test_password123",
        )

        # Compañía.
        self.company = Company.objects.create(
            name="Empresa de Prueba",
            code="TEST",
        )

        # Categoría del activo.
        self.category = Category.objects.create(
            name="Computadores",
        )

        # Empleado responsable.
        self.employee = Employee.objects.create(
            company=self.company,
            full_name="Empleado de Prueba",
        )

        # Activo inicialmente asignado.
        self.asset = Asset.objects.create(
            asset_tag="TEST-PC-001",
            category=self.category,
            company=self.company,
            status=AssetStatus.ASSIGNED,
        )

        # Asignación vigente.
        self.assignment = Assignment.objects.create(
            asset=self.asset,
            employee=self.employee,
            assigned_by=self.user,
            initial_condition="Equipo en buen estado.",
            status=AssignmentStatus.ACTIVE,
        )

    def test_return_assignment_successfully(self):
        """
        Comprueba que una devolución se registre correctamente.
        """

        returned_assignment = return_assignment(
            assignment_id=self.assignment.pk,
            condition="Equipo devuelto en buen estado.",
        )

        self.assignment.refresh_from_db()
        self.asset.refresh_from_db()

        self.assertEqual(
            returned_assignment.status,
            AssignmentStatus.RETURNED,
        )

        self.assertEqual(
            self.assignment.status,
            AssignmentStatus.RETURNED,
        )

        self.assertIsNotNone(self.assignment.returned_at)

        self.assertEqual(
            self.assignment.return_condition,
            "Equipo devuelto en buen estado.",
        )

        self.assertEqual(
            self.asset.status,
            AssetStatus.AVAILABLE,
        )

    def test_cannot_return_assignment_twice(self):
        """
        Impide devolver nuevamente una asignación ya cerrada.
        """

        return_assignment(
            assignment_id=self.assignment.pk,
            condition="Equipo en buen estado.",
        )

        with self.assertRaises(ValidationError):
            return_assignment(
                assignment_id=self.assignment.pk,
                condition="Segundo intento de devolución.",
            )

    def test_return_nonexistent_assignment(self):
        """
        Comprueba el comportamiento cuando la asignación no existe.
        """

        with self.assertRaises(ValidationError):
            return_assignment(
                assignment_id=uuid.uuid4(),
                condition="Equipo en buen estado.",
            )

    def test_return_requires_condition(self):
        """
        Impide registrar una devolución sin condición del activo.
        """

        with self.assertRaises(ValidationError):
            return_assignment(
                assignment_id=self.assignment.pk,
                condition="   ",
            )

        self.assignment.refresh_from_db()
        self.asset.refresh_from_db()

        self.assertEqual(
            self.assignment.status,
            AssignmentStatus.ACTIVE,
        )

        self.assertEqual(
            self.asset.status,
            AssetStatus.ASSIGNED,
        )

    def test_transaction_rolls_back_if_asset_update_fails(self):
        """
        Comprueba que no se cierre la asignación si falla
        la actualización del activo.
        """

        with patch(
            "inventory.models.Asset.save",
            side_effect=RuntimeError("Error simulado al actualizar activo"),
        ):
            with self.assertRaises(RuntimeError):
                return_assignment(
                    assignment_id=self.assignment.pk,
                    condition="Equipo en buen estado.",
                )

        self.assignment.refresh_from_db()
        self.asset.refresh_from_db()

        self.assertEqual(
            self.assignment.status,
            AssignmentStatus.ACTIVE,
        )

        self.assertIsNone(self.assignment.returned_at)

        self.assertIsNone(self.assignment.return_condition)

        self.assertEqual(
            self.asset.status,
            AssetStatus.ASSIGNED,
        )
	
    def test_create_assignment_successfully(self):
        """
        Comprueba que se cree una asignación y el activo
        pase a estado asignado.
        """

        available_asset = Asset.objects.create(
            asset_tag="TEST-PC-002",
            category=self.category,
            company=self.company,
            status=AssetStatus.AVAILABLE,
        )

        assignment = create_assignment(
            asset_id=available_asset.pk,
            employee_id=self.employee.pk,
            assigned_by=self.user,
            initial_condition="Equipo nuevo en buen estado.",
        )

        available_asset.refresh_from_db()

        self.assertEqual(
            assignment.status,
            AssignmentStatus.ACTIVE,
        )

        self.assertEqual(
            assignment.asset_id,
            available_asset.pk,
        )

        self.assertEqual(
            assignment.employee_id,
            self.employee.pk,
        )

        self.assertEqual(
            available_asset.status,
            AssetStatus.ASSIGNED,
        )

    def test_cannot_assign_unavailable_asset(self):
        """
        Impide asignar un activo que ya está asignado.
        """

        with self.assertRaises(ValidationError):
            create_assignment(
                asset_id=self.asset.pk,
                employee_id=self.employee.pk,
                assigned_by=self.user,
                initial_condition="Equipo en buen estado.",
            )

        self.asset.refresh_from_db()

        self.assertEqual(
            self.asset.status,
            AssetStatus.ASSIGNED,
        )

        self.assertEqual(
            Assignment.objects.filter(asset=self.asset).count(),
            1,
        )

    def test_create_assignment_requires_initial_condition(self):
        """
        Impide crear una asignación sin condición inicial.
        """

        available_asset = Asset.objects.create(
            asset_tag="TEST-PC-003",
            category=self.category,
            company=self.company,
            status=AssetStatus.AVAILABLE,
        )

        with self.assertRaises(ValidationError):
            create_assignment(
                asset_id=available_asset.pk,
                employee_id=self.employee.pk,
                assigned_by=self.user,
                initial_condition="   ",
            )

        self.assertFalse(
            Assignment.objects.filter(asset=available_asset).exists()
        )

        self.assertEqual(
            available_asset.status,
            AssetStatus.AVAILABLE,
        )

    def test_create_assignment_rolls_back_if_asset_update_fails(self):
        """
        Comprueba que no quede una asignación creada
        si falla la actualización del activo.
        """

        available_asset = Asset.objects.create(
            asset_tag="TEST-PC-004",
            category=self.category,
            company=self.company,
            status=AssetStatus.AVAILABLE,
        )

        with patch(
            "inventory.models.Asset.save",
            side_effect=RuntimeError("Error simulado al actualizar activo"),
        ):
            with self.assertRaises(RuntimeError):
                create_assignment(
                    asset_id=available_asset.pk,
                    employee_id=self.employee.pk,
                    assigned_by=self.user,
                    initial_condition="Equipo en buen estado.",
                )

        available_asset.refresh_from_db()

        self.assertEqual(
            available_asset.status,
            AssetStatus.AVAILABLE,
        )

        self.assertFalse(
            Assignment.objects.filter(asset=available_asset).exists()
        )


class AssignmentAdminPermissionsTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = AssignmentAdmin(
            Assignment,
            AdminSite(),
        )

    def create_request(self, role, is_staff=True):
        user = User.objects.create_user(
            username=f"usuario_{role}_{User.objects.count()}",
            password="test_password123",
            role=role,
            is_staff=is_staff,
        )

        request = self.factory.get("/admin/assignments/assignment/")
        request.user = user

        return request

    def test_administrator_permissions(self):
        request = self.create_request(Role.ADMINISTRATOR)

        self.assertTrue(self.admin.has_module_permission(request))
        self.assertTrue(self.admin.has_view_permission(request))
        self.assertTrue(self.admin.has_add_permission(request))
        self.assertTrue(self.admin.has_change_permission(request))
        self.assertFalse(self.admin.has_delete_permission(request))

    def test_technology_permissions(self):
        request = self.create_request(Role.TECHNOLOGY)

        self.assertTrue(self.admin.has_module_permission(request))
        self.assertTrue(self.admin.has_view_permission(request))
        self.assertTrue(self.admin.has_add_permission(request))
        self.assertTrue(self.admin.has_change_permission(request))
        self.assertFalse(self.admin.has_delete_permission(request))

    def test_consultation_permissions(self):
        request = self.create_request(Role.CONSULTATION)

        self.assertTrue(self.admin.has_module_permission(request))
        self.assertTrue(self.admin.has_view_permission(request))
        self.assertFalse(self.admin.has_add_permission(request))
        self.assertFalse(self.admin.has_change_permission(request))
        self.assertFalse(self.admin.has_delete_permission(request))

    def test_non_staff_user_has_no_access(self):
        request = self.create_request(
            Role.TECHNOLOGY,
            is_staff=False,
        )

        self.assertFalse(self.admin.has_module_permission(request))
        self.assertFalse(self.admin.has_view_permission(request))
        self.assertFalse(self.admin.has_add_permission(request))
        self.assertFalse(self.admin.has_change_permission(request))
        self.assertFalse(self.admin.has_delete_permission(request))

    def test_existing_assignment_fields_are_readonly(self):
        request = self.create_request(Role.TECHNOLOGY)

        assignment = Assignment()

        readonly_fields = self.admin.get_readonly_fields(
            request,
            assignment,
        )

        self.assertIn("asset", readonly_fields)
        self.assertIn("employee", readonly_fields)
        self.assertIn("status", readonly_fields)
        self.assertIn("assigned_at", readonly_fields)
        self.assertIn("returned_at", readonly_fields)
        self.assertIn("initial_condition", readonly_fields)
        self.assertIn("return_condition", readonly_fields)
        

class AssignmentPDFTestData:

    def setUp(self):
        super().setUp()

        self.company = Company.objects.create(
            name="Empresa PDF",
            code="PDF",
        )

        self.category = Category.objects.create(
            name="Portátiles PDF",
        )

        self.employee = Employee.objects.create(
            company=self.company,
            full_name="Empleado PDF",
        )

        self.asset = Asset.objects.create(
            asset_tag="PDF-PC-001",
            category=self.category,
            company=self.company,
            status=AssetStatus.ASSIGNED,
        )

        self.technician = User.objects.create_user(
            username="tecnico_pdf",
            password="test_password123",
            role=Role.TECHNOLOGY,
            is_staff=True,
        )

        self.assignment = Assignment.objects.create(
            asset=self.asset,
            employee=self.employee,
            assigned_by=self.technician,
            initial_condition="Equipo en buen estado",
            status=AssignmentStatus.ACTIVE,
        )

        self.url = reverse(
            "download_act_pdf",
            args=[self.assignment.pk],
        )

    def create_user(self, role, is_staff=True):
        return User.objects.create_user(
            username=f"pdf_{role}_{User.objects.count()}",
            password="test_password123",
            role=role,
            is_staff=is_staff,
        )

class AssignmentPDFPermissionsTests(
    AssignmentPDFTestData,
    TestCase,
):

    def test_anonymous_user_cannot_download(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_non_staff_user_cannot_download(self):
        user = self.create_user(
            Role.TECHNOLOGY,
            is_staff=False,
        )

        self.client.force_login(user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)

    def test_staff_user_without_pdf_gets_404(self):
        self.client.force_login(self.technician)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_consultation_user_without_pdf_gets_404(self):
        user = self.create_user(Role.CONSULTATION)
        self.client.force_login(user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

class AssignmentPDFDownloadTests(
    AssignmentPDFTestData,
    TransactionTestCase,
):


    def setUp(self):
        super().setUp()

        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)

        self.media_override = override_settings(
            MEDIA_ROOT=self.temp_media.name
        )
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.assignment.signed_act_pdf.save(
            "acta_prueba.pdf",
            ContentFile(b"%PDF-1.4\n% PDF de prueba\n"),
        )
    def test_technology_user_can_download_pdf(self):
        self.client.force_login(self.technician)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/pdf",
        )

        response.close()

    def test_consultation_user_can_download_pdf(self):
        user = self.create_user(Role.CONSULTATION)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        response.close()

    def test_non_staff_user_cannot_download_existing_pdf(self):
        user = self.create_user(
            Role.TECHNOLOGY,
            is_staff=False,
        )

        self.client.force_login(user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)