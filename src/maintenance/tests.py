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
