from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from assignments import utils
from assignments.models import Assignment, AssignmentStatus, ReturnReason
from assignments.tests import AssignmentPDFTestData
from inventory.models import Asset, AssetStatus


class DeliveryTests(AssignmentPDFTestData, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.technician)
        self.assets = [
            Asset.objects.create(asset_tag=code, category=self.category, company=self.company)
            for code in ("ENTREGA-01", "ENTREGA-02")
        ]
        self.add_url = reverse("admin:assignments_assignment_add")
        self.data = {
            "employee": self.employee.pk,
            "asset": self.assets[0].pk,
            "initial_condition": "Con cargador",
            "observations": "Entrega en oficina & accesorios",
            "activos-INITIAL_FORMS": 0,
            "activos-TOTAL_FORMS": 1,
            "activos-0-asset": self.assets[1].pk,
            "activos-0-initial_condition": "Con funda",
        }

    def test_delivery_pdf_contains_only_this_operation(self):
        with self.settings(MEDIA_ROOT=self.temp_media()), patch.object(
            utils, "render_to_string", wraps=utils.render_to_string,
        ) as rendered:
            response = self.client.post(self.add_url, self.data)
            self.assertEqual(response.status_code, 302)
            entries = Assignment.objects.filter(asset__in=self.assets)
            first = entries.get(asset=self.assets[0])
            second = entries.get(asset=self.assets[1])
            self.assertIsNotNone(first.delivery_id)
            self.assertEqual(first.delivery_id, second.delivery_id)
            self.assertEqual(first.signed_act_pdf.name, second.signed_act_pdf.name)
            self.assertEqual(first.history.first().history_user, self.technician)
            self.assertEqual(first.observations, self.data["observations"])
            self.assertEqual(second.initial_condition, "Con funda")
            self.assertEqual(first.asset.status, AssetStatus.ASSIGNED)
            html = utils.render_to_string(*rendered.call_args.args)
            for fragment in ("ENTREGA-01", "ENTREGA-02", "Con cargador", "Con funda",
                             "Entrega en oficina &amp; accesorios"):
                self.assertIn(fragment, html)
            self.assertNotIn(self.asset.asset_tag, html)
            self.assertContains(self.client.get(response.url), "ENTREGA-02")
            documents = self.client.get(reverse("admin:itam_documents"))
            self.assertContains(documents, "Entrega de activos", count=1)
            user = self.create_user(Role.CONSULTATION)
            self.client.force_login(user)
            download = self.client.get(reverse("download_act_pdf", args=[second.pk]))
            try:
                self.assertEqual(download.status_code, 200)
                self.assertTrue(next(iter(download.streaming_content)).startswith(b"%PDF"))
            finally:
                download.close()

    def temp_media(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def test_duplicate_is_rejected(self):
        response = self.client.post(self.add_url, {
            **self.data, "activos-0-asset": self.assets[0].pk,
        })
        self.assertContains(response, "evita repetirlo")
        self.assertEqual(Assignment.objects.count(), 1)

    def test_missing_condition_is_rejected(self):
        response = self.client.post(self.add_url, {
            **self.data, "activos-0-initial_condition": "",
        })
        self.assertIn("initial_condition", response.context["items"].forms[0].errors)
        self.assertEqual(Assignment.objects.count(), 1)

    def test_pdf_failure_reverts_assignments_and_asset_states(self):
        with patch("assignments.utils.generate_act_pdf", side_effect=OSError):
            response = self.client.post(self.add_url, self.data)
        self.assertContains(response, "No se pudo generar el PDF")
        self.assertContains(response, "Con funda")
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertEqual(Assignment.history.count(), 1)
        self.assertEqual(
            list(Asset.objects.filter(pk__in=[asset.pk for asset in self.assets])
                 .values_list("status", flat=True)),
            [AssetStatus.AVAILABLE, AssetStatus.AVAILABLE],
        )

    def test_consultation_cannot_create_a_delivery(self):
        self.client.force_login(self.create_user(Role.CONSULTATION))
        self.assertEqual(self.client.get(self.add_url).status_code, 403)
        self.assertEqual(self.client.post(self.add_url, self.data).status_code, 403)
        self.assertEqual(Assignment.objects.count(), 1)


    def test_assignment_detail_is_read_only_even_for_superusers(self):
        superuser = self.create_user(Role.ADMINISTRATOR)
        superuser.is_superuser = True
        superuser.save(update_fields=["is_superuser"])
        url = reverse("admin:assignments_assignment_change", args=[self.assignment.pk])
        history = reverse("admin:assignments_assignment_history", args=[self.assignment.pk])
        for user in (self.technician, self.create_user(Role.CONSULTATION), superuser):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                page = self.client.get(url)
                for label in ("Consultar asignación", "Solo consulta", "Custodia",
                              "Condición de entrega", history):
                    self.assertContains(page, label)
                self.assertNotContains(page, 'name="_save"')
                self.assertNotContains(page, 'id="assignment_form"')
                self.assertEqual(self.client.get(history).status_code, 200)
                self.assertEqual(self.client.post(url, {"observations": "Cambio"}).status_code, 403)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.observations)
        self.assertEqual(self.assignment.history.count(), 1)

    def test_loan_pdf_inventory_expiration_and_partial_return(self):
        self.technician.is_superuser = True
        self.technician.save(update_fields=["is_superuser"])
        loan_url = reverse("admin:assignments_assignment_loan")
        list_url = reverse("admin:assignments_assignment_changelist")
        changelist = self.client.get(list_url)
        self.assertContains(changelist, "<summary>Acciones</summary>", html=True)
        self.assertContains(changelist, f'<a href="{loan_url}">Prestar activos</a>', html=True)
        self.assertContains(changelist, f'<a href="{self.add_url}">Añadir historial de asignación</a>', html=True)
        self.assertContains(self.client.get(loan_url), 'type="date"')
        due_on = timezone.localdate() + timedelta(days=2)

        with self.settings(MEDIA_ROOT=self.temp_media()), patch.object(
            utils, "render_to_string", wraps=utils.render_to_string,
        ) as rendered:
            response = self.client.post(loan_url, {**self.data, "due_on": due_on.isoformat()})
            self.assertEqual(response.status_code, 302)
            first, second = [Assignment.objects.get(asset=asset) for asset in self.assets]
            self.assertEqual(first.due_on, due_on)
            self.assertEqual(second.history.first().due_on, due_on)
            self.assertEqual(first.signed_act_pdf.name, second.signed_act_pdf.name)
            html = utils.render_to_string(*rendered.call_args.args)
            for fragment in ("ACTA DE PRÉSTAMO DE ACTIVOS", due_on.strftime("%d/%m/%Y"),
                             "Con cargador", "Con funda", "Entrega en oficina &amp; accesorios"):
                self.assertIn(fragment, html)
            self.assertContains(self.client.get(response.url), "Préstamo registrado")
            self.assertNotContains(self.client.get(response.url), 'value="consolidated"')
            self.client.post(response.url, {"mode": "consolidated"})
            first.refresh_from_db()
            self.assertEqual(first.signed_act_pdf.name, second.signed_act_pdf.name)

            asset_url = reverse("admin:inventory_asset_change", args=[first.asset_id])
            self.assertContains(self.client.get(asset_url), "Préstamo registrado")
            self.assertContains(self.client.get(list_url, {"prestamo": "vigentes"}), "ENTREGA-01")
            with patch("django.utils.timezone.localdate", return_value=due_on + timedelta(days=1)):
                expired = self.client.get(list_url, {"prestamo": "vencidos"})
                self.assertContains(expired, "ENTREGA-01")
                self.assertContains(self.client.get(asset_url), "Vencido")
                self.assertEqual(first.asset.status, AssetStatus.ASSIGNED)
                self.assertEqual(first.status, AssignmentStatus.ACTIVE)

                return_url = reverse("admin:employees_employee_return_assets", args=[self.employee.pk])
                detail_url = reverse("admin:assignments_assignment_change", args=[first.pk])
                detail = self.client.get(detail_url)
                self.assertContains(detail, return_url)
                self.assertContains(detail, "Consultar préstamo")
                receipt = self.client.post(return_url, {
                    "assignments": [first.pk], "reason": ReturnReason.LOAN_END,
                    "condition": "Operativo al recibir", "observations": "Fin del préstamo",
                })
                self.assertEqual(receipt.status_code, 302)
                first.refresh_from_db()
                second.refresh_from_db()
                self.assertEqual(first.status, AssignmentStatus.RETURNED)
                self.assertEqual(first.due_on, due_on)
                self.assertEqual(first.return_condition, "Operativo al recibir")
                record = first.offboarding_item.offboarding_record
                self.assertTrue(record.pdf)
                self.assertEqual(record.return_reason, ReturnReason.LOAN_END)
                self.assertContains(self.client.get(receipt.url), "Fin del préstamo")
                self.assertEqual(first.asset.status, AssetStatus.AVAILABLE)
                self.assertEqual(second.status, AssignmentStatus.ACTIVE)
                self.assertEqual(second.asset.status, AssetStatus.ASSIGNED)
                returned = self.client.get(list_url, {"prestamo": "devueltos"})
                self.assertContains(returned, "ENTREGA-01")
                self.assertNotContains(returned, "ENTREGA-02")

            self.client.force_login(self.create_user(Role.CONSULTATION))
            download = self.client.get(reverse("download_act_pdf", args=[first.pk]))
            try:
                self.assertEqual(download.status_code, 200)
                self.assertIn("acta-de-prestamo.pdf", download["Content-Disposition"])
                self.assertTrue(next(iter(download.streaming_content)).startswith(b"%PDF"))
            finally:
                download.close()

    def test_loan_requires_a_current_or_future_date(self):
        loan_url = reverse("admin:assignments_assignment_loan")
        response = self.client.post(loan_url, self.data)
        self.assertIn("due_on", response.context["form"].errors)
        past = timezone.localdate() - timedelta(days=1)
        response = self.client.post(loan_url, {**self.data, "due_on": past.isoformat()})
        self.assertContains(response, "debe ser hoy o una fecha futura")
        self.assertEqual(Assignment.objects.count(), 1)

    def test_consultation_cannot_register_a_loan(self):
        loan_url = reverse("admin:assignments_assignment_loan")
        self.client.force_login(self.create_user(Role.CONSULTATION))
        self.assertNotContains(self.client.get(reverse("admin:assignments_assignment_changelist")), loan_url)
        self.assertEqual(self.client.get(loan_url).status_code, 403)
        response = self.client.post(loan_url, {**self.data, "due_on": timezone.localdate().isoformat()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Assignment.objects.count(), 1)
