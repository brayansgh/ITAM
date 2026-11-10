from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import Role
from assignments import utils
from assignments.models import Assignment
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
