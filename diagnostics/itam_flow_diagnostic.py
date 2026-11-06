"""Caracterización: los casos gap confirman defectos, no requisitos deseados."""
import tempfile
from django.test import TestCase, override_settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.urls import reverse
from accounts.models import User, Role
from organizations.models import Company, Site
from employees.models import Employee, EmployeeStatus
from inventory.models import Asset, AssetStatus, Category, DecommissionedAsset
from assignments.models import Assignment, AssignmentStatus, OffboardingRecord, OffboardingRecordItem
from assignments.services import create_assignment, return_assignment
from maintenance.models import MaintenanceRecord, MaintenanceType, MaintenanceStatus

class FlowDiagnostic(TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        setting=override_settings(MEDIA_ROOT=folder.name); setting.enable(); self.addCleanup(setting.disable)
        self.user=User.objects.create_superuser(username='diag_admin',password='Diagnostic-2026!')
        self.company=Company.objects.create(name='Empresa sintética',code='DIAG')
        self.employee=Employee.objects.create(company=self.company,full_name='Empleado sintético')
        self.category=Category.objects.create(name='Portátil sintético')
        self.asset=Asset.objects.create(company=self.company,category=self.category,asset_tag='DIAG-1',legacy_asset_tag='LEG-1')
    def assign(self,asset=None):
        return create_assignment(asset_id=(asset or self.asset).pk,employee_id=self.employee.pk,assigned_by=self.user,initial_condition='Buen estado')
    def ticket(self,**kw):
        data=dict(asset=self.asset,reported_by=self.user,type=MaintenanceType.CORRECTIVE,description='Diagnóstico sintético');data.update(kw)
        return MaintenanceRecord.objects.create(**data)
    def offboard_payload(self,a):
        return {'observations':'Prueba','items-TOTAL_FORMS':'1','items-INITIAL_FORMS':'0','items-MIN_NUM_FORMS':'0','items-MAX_NUM_FORMS':'1000','items-0-assignment_id':str(a.pk),'items-0-selected':'on','items-0-condition':'Buen estado','items-0-observations':'Prueba'}
    def test_01_complete_lifecycle_and_real_pdfs(self):
        from assignments.utils import generate_act_pdf
        a=self.assign()
        other=Asset.objects.create(company=self.company,category=self.category,asset_tag='DIAG-2')
        b=self.assign(other)
        self.employee.email='synthetic@example.test'; self.employee.save()
        generate_act_pdf(a);a.save(update_fields=['signed_act_pdf'])
        with a.signed_act_pdf.open('rb') as f:self.assertTrue(f.read(4)==b'%PDF')
        return_assignment(assignment_id=a.pk,condition='Recibido',returned_by=self.user)
        t=self.ticket(); t.status=MaintenanceStatus.COMPLETED;t.save()
        self.asset.refresh_from_db();self.assertEqual(self.asset.status,AssetStatus.AVAILABLE)
        self.employee.status=EmployeeStatus.RETIRO;self.employee.save()
        self.client.force_login(self.user)
        response=self.client.post(reverse('admin:employees_employee_process_offboarding',args=[self.employee.pk]),self.offboard_payload(b))
        self.assertEqual(response.status_code,200); self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(OffboardingRecord.objects.count(),1)
        self.assertFalse(Assignment.objects.filter(employee=self.employee,status=AssignmentStatus.ACTIVE).exists())
        self.assertTrue(OffboardingRecord.objects.get().pdf)
    def test_regression_02_maintenance_preserves_custody(self):
        a=self.assign();self.ticket();a.refresh_from_db()
        self.assertEqual(a.status,AssignmentStatus.ACTIVE)
        self.assertIsNone(a.returned_at);self.assertFalse(a.return_condition)
    def test_regression_03_completed_ticket_preserves_other_open_ticket(self):
        t=self.ticket();other=self.ticket()
        t.status=MaintenanceStatus.COMPLETED;t.save();self.asset.refresh_from_db()
        self.assertEqual(self.asset.status,AssetStatus.IN_MAINTENANCE)
        self.assertEqual(other.status,MaintenanceStatus.OPEN)
    def test_regression_04_retired_employee_cannot_receive_assets(self):
        self.employee.status=EmployeeStatus.RETIRO;self.employee.save()
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError): self.assign()
    def test_regression_05_manual_available_with_custody_is_rejected(self):
        from django.core.exceptions import ValidationError
        a=self.assign();self.asset.refresh_from_db();self.asset.status=AssetStatus.AVAILABLE
        with self.assertRaises(ValidationError): self.asset.save()
        a.refresh_from_db();self.assertEqual(a.status,AssignmentStatus.ACTIVE)
        self.asset.refresh_from_db();self.assertEqual(self.asset.status,AssetStatus.ASSIGNED)
    def test_regression_06_staff_without_permissions_cannot_offboard(self):
        a=self.assign();self.employee.status=EmployeeStatus.RETIRO;self.employee.save()
        staff=User.objects.create_user(username='diag_consult',role=Role.CONSULTATION,is_staff=True)
        self.assertFalse(staff.has_perm('employees.change_employee'))
        self.client.force_login(staff)
        response=self.client.post(reverse('admin:employees_employee_process_offboarding',args=[self.employee.pk]),self.offboard_payload(a))
        self.assertEqual(response.status_code,403)
        a.refresh_from_db();self.assertEqual(a.status,AssignmentStatus.ACTIVE)
    def test_gap_07_active_employee_can_be_offboarded(self):
        a=self.assign();self.client.force_login(self.user)
        response=self.client.post(reverse('admin:employees_employee_process_offboarding',args=[self.employee.pk]),self.offboard_payload(a))
        self.assertEqual(response.status_code,200)
        self.employee.refresh_from_db();self.assertEqual(self.employee.status,EmployeeStatus.ACTIVE)
    def test_regression_08_shared_physical_site_is_allowed(self):
        company=Company.objects.create(name='Otra empresa sintética',code='OTHER')
        site=Site.objects.create(company=company,name='Sede compartida')
        self.asset.site=site
        self.asset.full_clean();self.asset.save()
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site_id,site.pk)
        self.assertEqual(self.asset.company_id,self.company.pk)
    def test_gap_09_legacy_identifier_is_not_unique(self):
        other=Asset.objects.create(company=self.company,category=self.category,asset_tag='DIAG-OTHER',legacy_asset_tag='LEG-1')
        self.assertEqual(other.legacy_asset_tag,self.asset.legacy_asset_tag)
    def test_regression_10_lifecycle_widget_escapes_html(self):
        self.ticket(description='<b id="diag-html">sintético</b>')
        proxy=DecommissionedAsset.objects.get(pk=self.asset.pk)
        html=admin.site._registry[DecommissionedAsset].ciclo_de_vida(proxy)
        self.assertNotIn('<b id="diag-html">',str(html))
        self.assertIn("&lt;b",str(html))
    def test_regression_11_asset_card_has_operational_timeline(self):
        self.assign();self.ticket();self.client.force_login(self.user)
        response=self.client.get(reverse('admin:inventory_asset_change',args=[self.asset.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual({row['event_kind'] for row in response.context['asset_timeline']['rows']},{'assignment','maintenance'})
    def test_regression_12_search_finds_current_custodian(self):
        self.assign()
        from django.test import RequestFactory
        model_admin=admin.site._registry[Asset]
        request=RequestFactory().get('/');request.user=self.user
        results,_=model_admin.get_search_results(request,model_admin.get_queryset(request),self.employee.full_name)
        self.assertTrue(results.filter(pk=self.asset.pk).exists())
