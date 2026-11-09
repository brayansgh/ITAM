import tempfile
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, TransactionTestCase

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
        )

        # Asignación vigente.
        self.assignment = create_assignment(
            asset_id=self.asset.pk, employee_id=self.employee.pk,
            assigned_by=self.user, initial_condition="Equipo en buen estado.",
        )
        self.asset.refresh_from_db()

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
        )

        self.technician = User.objects.create_user(
            username="tecnico_pdf",
            password="test_password123",
            role=Role.TECHNOLOGY,
            is_staff=True,
        )

        self.assignment = create_assignment(
            asset_id=self.asset.pk, employee_id=self.employee.pk,
            assigned_by=self.technician, initial_condition="Equipo en buen estado",
        )
        self.asset.refresh_from_db()

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
    def test_returned_assignment_offers_return_pdf_and_keeps_previous_delivery(self):
        from assignments import utils

        previous = self.assignment.history.first()
        self.client.force_login(self.technician)
        act_url = reverse("admin:assignments_assignment_act", args=[self.assignment.pk])
        before = self.client.get(act_url)
        self.assertContains(before, "Generar nueva versión")
        self.assertEqual(self.assignment.history.first().signed_act_pdf, previous.signed_act_pdf)

        with patch.object(utils, "render_to_string", wraps=utils.render_to_string) as rendered:
            response = self.client.post(act_url, {"mode": "delivery"})
        self.assertRedirects(response, act_url)
        self.assertEqual([item.pk for item in rendered.call_args.args[1]["assignments"]], [self.assignment.pk])
        self.assertEqual(rendered.call_args.args[1]["employee"], self.employee)
        self.assignment.refresh_from_db()
        version = self.assignment.history.first()
        self.assertNotEqual(version.signed_act_pdf, previous.signed_act_pdf)
        self.assertEqual(version.history_user, self.technician)
        self.assertEqual(version.history_change_reason, "Generación de acta de entrega")
        from django.contrib.auth.models import Permission

        self.technician.user_permissions.add(Permission.objects.get(
            content_type__app_label="assignments", codename="view_offboardingrecord",
        ))
        from assignments.models import ReturnReason
        from assignments.services import register_active_returns
        from assignments.utils import AssignmentActError, issue_assignment_act

        record, _ = register_active_returns(
            employee=self.employee, assignments=[self.assignment], reason=ReturnReason.DAMAGE,
            condition="Recibido", observations="", actor=self.technician,
        )
        self.assertTrue(record.pdf)
        return_pdf = reverse("admin:assignments_offboardingrecord_view_pdf", args=[record.pk])
        self.assertEqual(record.items.get().assignment_id, self.assignment.pk)
        page = self.client.get(act_url + "?confirmada=1")
        self.assertContains(page, return_pdf)
        self.assertNotContains(page, "Generar nueva versión")
        self.assertEqual(self.client.post(act_url, {"mode": "delivery"}).status_code, 403)
        with self.assertRaisesMessage(AssignmentActError, "La asignación ya no está vigente"):
            issue_assignment_act(self.assignment.pk, actor=self.technician)
        history = self.client.get(reverse("admin:assignments_assignment_changelist"))
        self.assertContains(history, return_pdf)
        self.assertContains(history, "Acta de devolución")

        second_employee = Employee.objects.create(company=self.company, full_name="Segundo custodio")
        new_assignment = create_assignment(
            asset_id=self.asset.pk, employee_id=second_employee.pk, assigned_by=self.technician,
            initial_condition="Operativo",
        )
        self.assertEqual(Assignment.objects.count(), 2)
        self.assertContains(self.client.get(act_url), "Versiones anteriores")
        self.assertContains(self.client.get(reverse("admin:assignments_assignment_changelist")), act_url)

        reader = self.create_user(Role.CONSULTATION)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(act_url, {"mode": "delivery"}).status_code, 403)
        self.assertNotContains(self.client.get(act_url), "Generar nueva versión")
        wrong = reverse("download_act_pdf", args=[new_assignment.pk])
        self.assertEqual(self.client.get(wrong, {"version": previous.history_id}).status_code, 404)
        download = self.client.get(self.url, {"version": previous.history_id, "descargar": "1"})
        try:
            self.assertEqual(download.status_code, 200)
            self.assertTrue(download["Content-Disposition"].startswith("attachment;"))
            self.assertEqual(b"".join(download.streaming_content), b"%PDF-1.4\n% PDF de prueba\n")
        finally:
            download.close()

    def test_pdf_action_menu_offers_both_modalities_and_keeps_previous_file(self):
        from assignments import utils

        def assign(code):
            asset = Asset.objects.create(asset_tag=code, category=self.category, company=self.company)
            return create_assignment(asset_id=asset.pk, employee_id=self.employee.pk,
                                     assigned_by=self.technician, initial_condition="Operativo")

        additional = assign("CONSOL-01")
        returned = assign("CONSOL-02")
        retired = assign("CONSOL-03")
        return_assignment(assignment_id=returned.pk, condition="Recibido")
        Asset.objects.filter(pk=retired.asset_id).update(status=AssetStatus.DECOMMISSIONED)

        self.client.force_login(self.technician)
        act_url = reverse("admin:assignments_assignment_act", args=[self.assignment.pk])
        page = self.client.get(act_url + "?confirmada=1")
        for label in ("Acciones del PDF", "Abrir PDF", "Descargar PDF", "Generar nueva versión",
                      "Acta de entrega de esta asignación", "Acta consolidada del empleado", "Posponer"):
            self.assertContains(page, label)
        self.assertEqual(self.client.post(act_url, {"mode": "inválida"}).status_code, 400)
        original = self.assignment.signed_act_pdf.name
        previous = self.assignment.history.first().history_id
        count = Assignment.objects.count()
        with patch.object(utils, "render_to_string", wraps=utils.render_to_string) as rendered:
            response = self.client.post(act_url, {"mode": "consolidated"})
        self.assertRedirects(response, act_url)
        context = rendered.call_args.args[1]
        self.assertTrue(context["consolidated"])
        self.assertEqual({item.pk for item in context["assignments"]}, {self.assignment.pk, additional.pk})
        self.assignment.refresh_from_db()
        self.assertNotEqual(self.assignment.signed_act_pdf.name, original)
        self.assertTrue(self.assignment.signed_act_pdf.storage.exists(original))
        self.assertEqual(Assignment.objects.count(), count)
        self.assertContains(self.client.get(act_url), f"?version={previous}&amp;descargar=1")

    def test_generation_failure_preserves_assignment_and_existing_document(self):
        self.client.force_login(self.technician)
        act_url = reverse("admin:assignments_assignment_act", args=[self.assignment.pk])
        original = self.assignment.signed_act_pdf.name
        versions = self.assignment.history.count()
        with patch("assignments.utils.generate_act_pdf", side_effect=OSError):
            response = self.client.post(act_url, {"mode": "delivery"}, follow=True)
        self.assertContains(response, "La asignación sigue registrada.")
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.signed_act_pdf.name, original)
        self.assertEqual(self.assignment.history.count(), versions)
        self.assertEqual(Assignment.objects.count(), 1)

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

class PrivateMediaRoutingTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_media_is_not_served_even_in_debug(self):
        with tempfile.TemporaryDirectory() as media_root:
            from pathlib import Path
            Path(media_root, "synthetic.pdf").write_bytes(b"%PDF-1.4 synthetic")
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get("/media/synthetic.pdf")
                self.assertEqual(response.status_code, 404)


class PrivateAssignmentAdminFormTests(SimpleTestCase):
    def test_pdf_file_cannot_be_edited_in_admin(self):
        request = RequestFactory().get("/admin/")
        request.user = User(role=Role.TECHNOLOGY, is_staff=True, is_active=True)
        model_admin = AssignmentAdmin(Assignment, AdminSite())
        form = model_admin.get_form(request)
        self.assertNotIn("signed_act_pdf", form.base_fields)
        self.assertIn("download_pdf", model_admin.get_readonly_fields(request))
