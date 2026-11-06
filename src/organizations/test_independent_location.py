from django.test import TestCase
from django.forms import modelform_factory
from organizations.models import Site, Company
from inventory.models import Asset, Category

class IndependentLocationTests(TestCase):
    def test_location_without_company_can_be_shared_by_assets(self):
        location = Site(name="Ciudad sintética", city="Ciudad sintética")
        location.full_clean()
        location.save()
        category = Category.objects.create(name="Equipo")
        for code in ("A", "B"):
            company = Company.objects.create(name=code, code=code)
            asset = Asset(asset_tag=code, company=company, site=location, category=category)
            asset.full_clean()
            asset.save()
            self.assertEqual(asset.site_id, location.pk)
        location.refresh_from_db()
        self.assertIsNone(location.company_id)
