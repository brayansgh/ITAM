from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from data_imports.models import StagingAsset, ImportStatus
from inventory.models import Asset
from employees.models import Employee
from assignments.models import Assignment, AssignmentStatus

User = get_user_model()

class Command(BaseCommand):
    help = 'Genera las asignaciones automáticamente de los activos importados que tenían empleado.'

    def handle(self, *args, **kwargs):
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            self.stdout.write(self.style.ERROR("Error: No se encontró administrador para autorizar la asignación."))
            return

        # Filtrar registros importados que sí tenían un empleado en el Excel
        imported_with_user = StagingAsset.objects.filter(
            status=ImportStatus.IMPORTED
        ).exclude(employee_name__isnull=True).exclude(employee_name__exact='')

        count = 0
        with transaction.atomic():
            for stg in imported_with_user:
                # Buscar correspondencia de activo
                asset = Asset.objects.filter(serial_number=stg.serial_number).first()
                if not asset and stg.legacy_asset_tag:
                    asset = Asset.objects.filter(legacy_asset_tag=stg.legacy_asset_tag).first()
                    
                # Buscar correspondencia de empleado
                emp = None
                if stg.employee_document:
                    emp = Employee.objects.filter(document_number=stg.employee_document).first()
                if not emp:
                    emp = Employee.objects.filter(full_name=stg.employee_name).first()

                # Vincular y generar el registro histórico
                if asset and emp:
                    exists = Assignment.objects.filter(asset=asset, status=AssignmentStatus.ACTIVE).exists()
                    if not exists:
                        Assignment.objects.create(
                            asset=asset,
                            employee=emp,
                            assigned_by=admin_user,
                            status=AssignmentStatus.ACTIVE,
                            initial_condition="Migración inicial desde el Excel de inventario histórico.",
                            observations=stg.observations or "Sin observaciones previas."
                        )
                        asset.status = 'ASSIGNED'
                        asset.save()
                        count += 1

        self.stdout.write(self.style.SUCCESS(f"¡Éxito! Se vincularon automáticamente {count} equipos a sus respectivos usuarios."))
