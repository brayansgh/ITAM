from simple_history.utils import bulk_update_with_history
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.exceptions import ValidationError
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
                
                key = (site.company_id, clean_name)
                if key not in site_map:
                    site.name = clean_name
                    site.save()
                    site_map[key] = site
                else:
                    master_site = site_map[key]
                    # Reasignar activos y empleados a la sede principal
                    self.move_relation(Asset.objects.filter(site=site), "site", master_site)
                    self.move_relation(Employee.objects.filter(site=site), "site", master_site)
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
                
                key = (area.company_id, clean_name)
                if key not in area_map:
                    area.name = clean_name
                    area.save()
                    area_map[key] = area
                else:
                    master_area = area_map[key]
                    # Reasignar empleados al área principal
                    self.move_relation(Employee.objects.filter(area=area), "area", master_area)
                    area.delete()
                    areas_deleted += 1

            self.stdout.write(f"Áreas unificadas: {areas_deleted} duplicados eliminados.")
            self.stdout.write(self.style.SUCCESS("Tratamiento de datos finalizado con éxito."))

    def move_relation(self, queryset, field, target):
        instances = list(queryset.select_for_update())
        if any(instance.company_id != target.company_id for instance in instances):
            raise ValidationError("No se pueden fusionar relaciones entre compañías diferentes.")
        for instance in instances:
            setattr(instance, field, target)
        # Conserva la semántica original: no dispara sincronizaciones de estado.
        bulk_update_with_history(instances, queryset.model, [field], batch_size=500)
