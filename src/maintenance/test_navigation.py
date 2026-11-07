from html.parser import HTMLParser
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import Permission
from accounts.models import User
from inventory.models import Asset, Category
from organizations.models import Company
from .models import MaintenanceRecord, MaintenanceStatus, MaintenanceType


class TicketNavigationTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser(username="ticket_navigator",password="Test-4826!")
        company=Company.objects.create(name="Empresa",code="NAV")
        category=Category.objects.create(name="Equipo")
        self.asset=Asset.objects.create(asset_tag="NAV-001",company=company,category=category)
        self.ticket=MaintenanceRecord.objects.create(asset=self.asset,reported_by=self.user,
                    type=MaintenanceType.CORRECTIVE,description="Ticket sintético")
        self.list_url=reverse("admin:maintenance_maintenancerecord_changelist")
        self.ticket_url=reverse("admin:maintenance_maintenancerecord_change",args=[self.ticket.pk])
        self.asset_url=reverse("admin:inventory_asset_change",args=[self.asset.pk])
        self.client.force_login(self.user)

    def test_list_separates_ticket_management_from_asset_link_without_nested_anchors(self):
        response=self.client.get(self.list_url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context["title"], "Mantenimiento")
        self.assertContains(response,"Gestionar ticket")
        self.assertContains(response,self.ticket_url)
        self.assertContains(response,self.asset_url)
        self.assertEqual(response.context['cl'].list_display_links,('ticket_reference',))
        class Anchors(HTMLParser):
            depth=0
            nested=False
            def handle_starttag(self,tag,attrs):
                if tag=='a':
                    if self.depth:self.nested=True
                    self.depth+=1
            def handle_endtag(self,tag):
                if tag=='a':self.depth=max(0,self.depth-1)
        parser=Anchors();parser.feed(response.content.decode())
        self.assertFalse(parser.nested)

    def test_management_link_opens_editable_ticket_and_can_save(self):
        response=self.client.get(self.ticket_url)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['has_change_permission'])
        data={'asset':str(self.asset.pk),'type':MaintenanceType.CORRECTIVE,
              'status':MaintenanceStatus.IN_PROGRESS,'description':'Trabajo en curso',
              'reported_by':str(self.user.pk),'documents-TOTAL_FORMS':'0',
              'documents-INITIAL_FORMS':'0','documents-MIN_NUM_FORMS':'0','documents-MAX_NUM_FORMS':'3','_save':'Guardar'}
        self.assertEqual(self.client.post(self.ticket_url,data).status_code,302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status,MaintenanceStatus.IN_PROGRESS)
        self.assertEqual(self.ticket.description,'Trabajo en curso')

    def test_closed_ticket_has_consultation_link_and_rejects_editing(self):
        self.ticket.status=MaintenanceStatus.COMPLETED;self.ticket.save()
        response=self.client.get(self.list_url)
        self.assertContains(response,'Ver ticket')
        self.assertNotContains(response,'Gestionar ticket')
        self.assertEqual(self.client.post(self.ticket_url,{'description':'Cambio prohibido'}).status_code,403)

    def test_view_only_user_sees_consultation_and_cannot_edit(self):
        viewer=User.objects.create_user(username='ticket_viewer',is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='maintenance',codename='view_maintenancerecord'))
        self.client.force_login(viewer)
        response=self.client.get(self.list_url)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Ver ticket')
        self.assertNotContains(response,'Gestionar ticket')
        self.assertNotContains(response,self.asset_url)
        self.assertEqual(self.client.post(self.ticket_url,{'status':MaintenanceStatus.IN_PROGRESS}).status_code,403)


    def test_decommission_upload_then_close(self):
        from tempfile import TemporaryDirectory
        from django.core.files.uploadedfile import SimpleUploadedFile
        from inventory.models import AssetStatus
        from .models import DecommissionReason

        ticket = MaintenanceRecord.objects.create(
            asset=self.asset, reported_by=self.user, type=MaintenanceType.DECOMMISSION,
            description="Evaluación de baja",
        )
        url = reverse("admin:maintenance_decommission_change", args=[ticket.pk])
        form = self.client.get(url)
        self.assertContains(form, 'enctype="multipart/form-data"')
        self.assertContains(form, "Motivo de baja")
        self.assertNotContains(form, 'name="provider"')
        self.assertNotContains(self.client.get(self.ticket_url), 'name="decommission_reason"')
        listing = self.client.get(reverse("admin:itam_decommissions"))
        self.assertContains(listing, f'<a class="button" href="{url}">Abrir registro</a>')
        data = {
            "asset": str(self.asset.pk), "reported_by": str(self.user.pk),
            "description": ticket.description, "status": MaintenanceStatus.OPEN,
            "decommission_reason": DecommissionReason.DAMAGE,
            "documents-TOTAL_FORMS": "1", "documents-INITIAL_FORMS": "0",
            "_save": "Guardar",
        }
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            response = self.client.post(url, {
                **data, "documents-0-document": SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4 synthetic"),
            })
            self.assertRedirects(response, url, fetch_redirect_response=False)
            document = ticket.documents.get()
            self.assertTrue(document.document.storage.exists(document.document.name))
            self.assertContains(self.client.get(url), reverse("admin:maintenance_document_download", args=[document.pk]))
            self.ticket.status = MaintenanceStatus.CANCELLED
            self.ticket.save()
            data.update({
                "status": MaintenanceStatus.COMPLETED, "resolution_notes": "Disposición de prueba documentada.",
                "documents-INITIAL_FORMS": "1", "documents-0-id": str(document.pk),
            })
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 302)
            ticket.refresh_from_db()
            self.asset.refresh_from_db()
            self.assertEqual(ticket.decommission_reason, DecommissionReason.DAMAGE)
            self.assertEqual(ticket.status, MaintenanceStatus.COMPLETED)
            self.assertEqual(self.asset.status, AssetStatus.DECOMMISSIONED)
            self.assertEqual(ticket.documents.get().pk, document.pk)


    def test_decommission_can_upload_evidence_and_complete_in_one_submit(self):
        from tempfile import TemporaryDirectory
        from django.core.files.uploadedfile import SimpleUploadedFile
        from inventory.models import AssetStatus
        from .models import DecommissionReason

        self.ticket.status = MaintenanceStatus.CANCELLED
        self.ticket.save()
        ticket = MaintenanceRecord.objects.create(
            asset=self.asset, reported_by=self.user, type=MaintenanceType.DECOMMISSION,
            description="Evaluación de baja",
        )
        url = reverse("admin:maintenance_decommission_change", args=[ticket.pk])
        data = {
            "asset": str(self.asset.pk), "reported_by": str(self.user.pk),
            "description": ticket.description, "status": MaintenanceStatus.COMPLETED,
            "resolution_notes": "Disposición documentada.", "documents-TOTAL_FORMS": "1",
            "documents-INITIAL_FORMS": "0", "_save": "Guardar",
        }
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            invalid = self.client.post(url, {
                **data, "documents-0-document": SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4 synthetic"),
            })
            self.assertContains(invalid, "Selecciona el motivo de la baja")
            self.assertContains(invalid, 'name="documents-0-document"')
            self.assertTrue(invalid.context["has_change_permission"])
            self.assertFalse(ticket.documents.exists())
            response = self.client.post(url, {
                **data, "decommission_reason": DecommissionReason.DAMAGE,
                "documents-0-document": SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4 synthetic"),
            })
            self.assertEqual(response.status_code, 302)
            ticket.refresh_from_db()
            self.asset.refresh_from_db()
            self.assertEqual(ticket.status, MaintenanceStatus.COMPLETED)
            self.assertEqual(self.asset.status, AssetStatus.DECOMMISSIONED)
            document = ticket.documents.get()
            self.assertTrue(document.document.storage.exists(document.document.name))
            self.assertEqual(self.client.post(url, data).status_code, 403)
