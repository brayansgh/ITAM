from django.core.management.base import BaseCommand
from django.db import transaction
from organizations.models import Site, Area
from inventory.models import Asset
from employees.models import Employee

class Command(BaseCommand):
    help = 'Limpia espacios en blanco y fusiona Sedes y Áreas duplicadas'

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            self.stdout.write("Iniciando la depuración y unificación de Sedes...")
            
            # 1. Depurar Sedes
            sites = list(Site.objects.all())
            site_map = {}
            sites_deleted = 0

            for site in sites:
                clean_name = site.name.strip().upper()
                
                if clean_name not in site_map:
                    site.name = clean_name
                    site.save()
                    site_map[clean_name] = site
                else:
                    master_site = site_map[clean_name]
                    # Reasignar activos y empleados a la sede principal
                    Asset.objects.filter(site=site).update(site=master_site)
                    Employee.objects.filter(site=site).update(site=master_site)
                    site.delete()
                    sites_deleted += 1

            self.stdout.write(f"Sedes unificadas: {sites_deleted} duplicados eliminados.")

            self.stdout.write("Iniciando la depuración y unificación de Áreas...")
            
            # 2. Depurar Áreas
            areas = list(Area.objects.all())
            area_map = {}
            areas_deleted = 0

            for area in areas:
                clean_name = area.name.strip().upper()
                
                if clean_name not in area_map:
                    area.name = clean_name
                    area.save()
                    area_map[clean_name] = area
                else:
                    master_area = area_map[clean_name]
                    # Reasignar empleados al área principal
                    Employee.objects.filter(area=area).update(area=master_area)
                    area.delete()
                    areas_deleted += 1

            self.stdout.write(f"Áreas unificadas: {areas_deleted} duplicados eliminados.")
            self.stdout.write(self.style.SUCCESS("Tratamiento de datos finalizado con éxito."))
