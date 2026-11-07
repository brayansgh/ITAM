from django.contrib import admin
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.middleware.csrf import _get_new_csrf_string
from accounts.models import User
from organizations.models import Company
from .models import Asset, AssetGroup, Category, Brand, ModelAsset, AssetWarranty
from .forms import AssetRegistrationForm


class IndependentIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='independent_operator', password='Temporary-test-4826!')
        self.owner = Company.objects.create(name='Compañía sintética', code='ACE')
        self.category = Category.objects.create(name='Radioteléfono', group=AssetGroup.TELEPHONY)
        self.legacy = Category.objects.create(name='Tipo legado', group=AssetGroup.COMPUTING)
        self.motorola = Brand.objects.create(name='Motorola')
        self.other = Brand.objects.create(name='Otra marca')
        self.model = ModelAsset.objects.create(name='DTR720', brand=self.motorola, category=self.legacy)
        self.asset = Asset.objects.create(company=self.owner, owner_company=self.owner, category=self.category)
        self.client.force_login(self.user)

    def data(self):
        data = {'asset_tag': self.asset.asset_tag, 'group': 'TELEPHONY', 'category': str(self.category.pk), 'company': str(self.owner.pk),
                'owner_company': str(self.owner.pk), 'status': 'AVAILABLE', 'property_type': 'OWNED',
                'brand': str(self.other.pk), 'model': str(self.model.pk), '_save': 'Guardar'}
        for prefix in ['specs', 'network', 'warranties']:
            data.update({prefix+'-TOTAL_FORMS': '0', prefix+'-INITIAL_FORMS': '0', prefix+'-MIN_NUM_FORMS': '0', prefix+'-MAX_NUM_FORMS': '1000'})
        return data

    def test_type_brand_and_model_are_independent_and_optional(self):
        for brand, model in [(self.other.pk, self.model.pk), (self.other.pk, ''), ('', self.model.pk), ('', '')]:
            with self.subTest(brand=bool(brand), model=bool(model)):
                data = self.data();data.update(brand=str(brand), model=str(model))
                form = AssetRegistrationForm(data=data, instance=Asset.objects.get(pk=self.asset.pk))
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                self.asset.refresh_from_db()
                self.assertEqual(str(self.asset.brand_id) if self.asset.brand_id else '', str(brand))
                self.assertEqual(str(self.asset.model_id) if self.asset.model_id else '', str(model))

    def test_model_catalog_does_not_require_brand_or_type(self):
        model = ModelAsset.objects.create(name='Modelo independiente')
        self.assertEqual(str(model), 'Modelo independiente')
        url = reverse('admin:inventory_modelasset_add')
        self.assertEqual(self.client.post(url, {'name': 'Otro modelo', '_save': 'Guardar'}).status_code, 302)
        self.assertFalse(ModelAsset.objects.get(name='Otro modelo').brand_id)

    def test_brand_change_and_warranty_save_with_enforced_csrf(self):
        client = Client(enforce_csrf_checks=True);client.force_login(self.user)
        url = reverse('admin:inventory_asset_change', args=[self.asset.pk])
        client.get(url+'?editar=1')
        stale = client.cookies['csrftoken'].value
        data = self.data()
        data.update({'csrfmiddlewaretoken': stale, 'warranties-TOTAL_FORMS': '1',
                     'warranties-0-supplier': 'Proveedor sintético', 'warranties-0-purchase_date': '2026-11-01',
                     'warranties-0-warranty_start': '2026-11-01', 'warranties-0-warranty_end': '2027-11-01'})
        # Simula la cookie actualizada por iniciar sesión en otra pestaña.
        client.cookies['csrftoken'] = _get_new_csrf_string()
        self.assertEqual(client.post(url, data).status_code, 403)
        self.assertEqual(AssetWarranty.objects.count(), 0)
        token = client.get(reverse('admin:itam_form_token'))
        self.assertEqual(token.status_code, 200)
        self.assertIn('no-store', token['Cache-Control'])
        data['csrfmiddlewaretoken'] = token.json()['csrfToken']
        response = client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.brand, self.other)
        self.assertEqual(self.asset.model, self.model)
        self.assertEqual(AssetWarranty.objects.get(asset=self.asset).purchase_date.isoformat(), '2026-11-01')
        self.assertEqual(self.asset.history.first().history_user, self.user)
        self.assertEqual(self.asset.warranties.first().history.first().history_user, self.user)

    def test_token_endpoint_does_not_grant_edit_permission(self):
        viewer = User.objects.create_user(username='limited', is_staff=True, role='OTHER')
        client=Client(enforce_csrf_checks=True);client.force_login(viewer)
        token = client.get(reverse('admin:itam_form_token')).json()['csrfToken']
        self.assertEqual(client.post(reverse('admin:itam_form_token'), {'csrfmiddlewaretoken': token}).status_code, 405)
        self.assertEqual(client.post(reverse('admin:inventory_asset_change', args=[self.asset.pk]), {**self.data(), 'csrfmiddlewaretoken':token}).status_code, 403)
        client.logout()
        self.assertEqual(client.get(reverse('admin:itam_form_token')).status_code, 302)


class BrandMigrationTests(TransactionTestCase):
    def test_legacy_brands_are_preserved_with_new_audit_without_rewriting_previous(self):
        old=[('inventory','0009_etiquetas_en_espanol')]
        target=[('inventory','0011_conservar_marcas_legadas')]
        executor=MigrationExecutor(connection);executor.migrate(old)
        apps=executor.loader.project_state(old).apps
        A=apps.get_model('inventory','Asset');H=apps.get_model('inventory','HistoricalAsset')
        B=apps.get_model('inventory','Brand');M=apps.get_model('inventory','ModelAsset')
        C=apps.get_model('inventory','Category');Co=apps.get_model('organizations','Company')
        try:
            co=Co.objects.create(name='Empresa de migración',code='LEG')
            category=C.objects.create(name='Tipo legado')
            brand=B.objects.create(name='Marca legada');model=M.objects.create(name='Modelo legado',brand=brand,category=category)
            assets=[];old_ids=[]
            for status in ['AVAILABLE','DECOMMISSIONED']:
                a=A.objects.create(asset_tag='LEG-'+status,company=co,category=category,model=model,status=status)
                values={f.attname:getattr(a,f.attname) for f in A._meta.concrete_fields}
                from django.utils import timezone
                h=H.objects.create(**values,history_type='+',history_date=timezone.now())
                old_ids.append(h.history_id);assets.append(a)
            before=list(H.objects.filter(history_id__in=old_ids).values())
            MigrationExecutor(connection).migrate(target)
            for a in assets:
                current=Asset.objects.get(pk=a.pk)
                self.assertEqual(current.brand_id,brand.pk)
                self.assertEqual(current.model_id,model.pk)
                self.assertEqual(current.status,a.status)
                self.assertEqual(current.history.count(),2)
                self.assertIsNone(current.history.first().history_user)
                self.assertIn('copia exacta', current.history.first().history_change_reason)
            after=list(Asset.history.filter(history_id__in=old_ids).values())
            self.assertEqual([{k:v for k,v in row.items() if k!='brand_id'} for row in after],before)
            self.assertTrue(all(row['brand_id'] is None for row in after))
        finally:
            MigrationExecutor(connection).migrate(target)
