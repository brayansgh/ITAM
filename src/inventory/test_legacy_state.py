from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from organizations.models import Company, Site
from employees.models import Employee
from inventory.models import Asset, AssetStatus, AssetSpecs, Category
from assignments.services import create_assignment

class LegacyStateFormTests(TestCase):
    def test_maintenance_from_legacy_available_with_custody(self):
        company=Company.objects.create(name='Prueba',code='LEGACY')
        category=Category.objects.create(name='Prueba')
        asset=Asset.objects.create(asset_tag='LEGACY-001',company=company,category=category)
        operator=User.objects.create_superuser(username='legacy_operator',password='Test-4826!')
        employee=Employee.objects.create(company=company,full_name='Persona sintética')
        create_assignment(asset_id=asset.pk,employee_id=employee.pk,assigned_by=operator,initial_condition='Buen estado')
        Asset.objects.filter(pk=asset.pk).update(status=AssetStatus.AVAILABLE)
        asset.refresh_from_db()
        specs=AssetSpecs.objects.create(asset=asset,ram='8 GB')
        self.client.force_login(operator)
        data={'asset_tag':asset.asset_tag,'category':str(category.pk),'company':str(company.pk),
              'status':AssetStatus.MAINTENANCE,'property_type':'OWNED','_save':'Guardar',
              'specs-TOTAL_FORMS':'1','specs-INITIAL_FORMS':'1','specs-0-id':str(specs.pk),
              'specs-0-asset':str(asset.pk),'specs-0-ram':'8 GB'}
        for prefix in ('specs','network','warranties'):
            data.setdefault(prefix+'-TOTAL_FORMS','0');data.setdefault(prefix+'-INITIAL_FORMS','0')
            data[prefix+'-MIN_NUM_FORMS']='0';data[prefix+'-MAX_NUM_FORMS']='1000'
        response=self.client.post(reverse('admin:inventory_asset_change',args=[asset.pk]),data)
        self.assertEqual(response.status_code,302)
        asset.refresh_from_db()
        self.assertEqual(asset.status,AssetStatus.IN_MAINTENANCE)

    def test_old_completed_decommission_is_not_reapplied_by_new_maintenance(self):
        from maintenance.models import MaintenanceRecord, MaintenanceStatus, MaintenanceType
        company=Company.objects.create(name='Prueba',code='OLD')
        category=Category.objects.create(name='Prueba')
        operator=User.objects.create_superuser(username='old_operator',password='Test-4826!')
        asset=Asset.objects.create(asset_tag='OLD-001',company=company,category=category)
        employee=Employee.objects.create(company=company,full_name='Persona sintética')
        assignment=create_assignment(asset_id=asset.pk,employee_id=employee.pk,assigned_by=operator,initial_condition='Buen estado')
        historical=MaintenanceRecord.objects.create(asset=asset,reported_by=operator,type=MaintenanceType.CORRECTIVE,
                        status=MaintenanceStatus.COMPLETED,description='Registro histórico')
        # Solo fixture temporal: reproducir la inconsistencia histórica reportada.
        MaintenanceRecord.objects.filter(pk=historical.pk).update(type=MaintenanceType.DECOMMISSION)
        Asset.objects.filter(pk=asset.pk).update(status=AssetStatus.AVAILABLE)
        self.client.force_login(operator)
        data={'asset_tag':asset.asset_tag,'category':str(category.pk),'company':str(company.pk),
              'status':AssetStatus.MAINTENANCE,'property_type':'OWNED','_save':'Guardar'}
        for prefix in ('specs','network','warranties'):
            data.update({prefix+'-TOTAL_FORMS':'0',prefix+'-INITIAL_FORMS':'0',prefix+'-MIN_NUM_FORMS':'0',prefix+'-MAX_NUM_FORMS':'1000'})
        response=self.client.post(reverse('admin:inventory_asset_change',args=[asset.pk]),data)
        self.assertEqual(response.status_code,302)
        asset.refresh_from_db();assignment.refresh_from_db();historical.refresh_from_db()
        self.assertEqual(asset.status,AssetStatus.IN_MAINTENANCE)
        self.assertEqual(assignment.status,'ACTIVE')
        self.assertEqual(historical.status,MaintenanceStatus.COMPLETED)
        self.assertEqual(asset.maintenances.filter(status=MaintenanceStatus.OPEN).count(),1)
        # La recepción y el cierre de la reparación tampoco reejecutan la baja antigua.
        from assignments.services import return_assignment
        return_assignment(assignment_id=assignment.pk,condition='Recibido')
        repair=asset.maintenances.get(status=MaintenanceStatus.OPEN)
        repair.status=MaintenanceStatus.COMPLETED;repair.save()
        asset.refresh_from_db();self.assertEqual(asset.status,AssetStatus.AVAILABLE)

    def test_location_edit_does_not_require_return_for_unchanged_legacy_state(self):
        company=Company.objects.create(name='Prueba',code='LOCATION')
        category=Category.objects.create(name='Prueba')
        operator=User.objects.create_superuser(username='location_operator',password='Test-4826!')
        asset=Asset.objects.create(asset_tag='LOCATION-001',company=company,category=category)
        employee=Employee.objects.create(company=company,full_name='Persona sintética')
        create_assignment(asset_id=asset.pk,employee_id=employee.pk,assigned_by=operator,initial_condition='Buen estado')
        Asset.objects.filter(pk=asset.pk).update(status=AssetStatus.AVAILABLE)
        site=Site.objects.create(name='Ubicación física sin compañía')
        self.client.force_login(operator)
        data={'asset_tag':asset.asset_tag,'category':str(category.pk),'company':str(company.pk),
              'site':str(site.pk),'status':AssetStatus.AVAILABLE,'property_type':'OWNED','_save':'Guardar'}
        for prefix in ('specs','network','warranties'):
            data.update({prefix+'-TOTAL_FORMS':'0',prefix+'-INITIAL_FORMS':'0',prefix+'-MIN_NUM_FORMS':'0',prefix+'-MAX_NUM_FORMS':'1000'})
        response=self.client.post(reverse('admin:inventory_asset_change',args=[asset.pk]),data)
        self.assertEqual(response.status_code,302)
        asset.refresh_from_db()
        self.assertEqual(asset.site_id,site.pk)
        self.assertEqual(asset.status,AssetStatus.AVAILABLE)
        self.assertEqual(asset.assignments.filter(status='ACTIVE').count(),1)
