from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from data_imports.models import StagingAsset, ImportStatus
from organizations.models import Company, Site, Area
from inventory.models import Category, Brand, ModelAsset, Asset, AssetSpecs, AssetNetwork

class Command(BaseCommand):
    help = 'Migra los registros aprobados de Staging a Producción'

    def add_arguments(self, parser):
        parser.add_argument('--owner-code', choices=('ACE', 'SOL'), help='Propietaria explícita del lote; no se infiere de la administradora.')

    def handle(self, *args, **kwargs):
        approved = StagingAsset.objects.filter(batch_id__isnull=True, status=ImportStatus.APPROVED).order_by('row_number')
        count = approved.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING("No hay registros marcados como 'Aprobado para Importar'."))
            return
        if not kwargs.get('owner_code'):
            raise CommandError('Indica --owner-code ACE o SOL para este lote. La propietaria no se infiere de la compañía administradora.')
        owner = Company.objects.filter(code=kwargs['owner_code']).first()
        if owner is None:
            raise CommandError('No existe la propietaria indicada.')
            
        self.stdout.write(f"Iniciando la migración de {count} registros aprobados...")
        success_count = 0
        error_count = 0
        
        
        for stg in approved:
            try:
                if stg.employee_name or stg.employee_document:
                    raise CommandError(
                        'La fila incluye un custodio y no tiene condición de entrega. '
                        'Registra la custodia mediante el flujo de asignación.'
                    )
                with transaction.atomic():
                    stg = approved.select_for_update().filter(pk=stg.pk).first()
                    if stg is None:
                        continue
                    # 1. Crear o recuperar Organizaciones
                    comp_name = stg.company or 'Desconocida'
                    comp, _ = Company.objects.get_or_create(name=comp_name, defaults={'code': comp_name[:3].upper()})
                    
                    site, _ = Site.objects.get_or_create(name=stg.site or 'Principal', company=comp)
                    
                    # CORRECCIÓN: El Área está vinculada a la Compañía, no a la Sede
                    Area.objects.get_or_create(name=stg.area or 'General', company=comp)
                    
                    # 2. Clasificación del Inventario
                    cat = Category.objects.exclude(group='').filter(name__iexact=stg.element or '').first()
                    if cat is None:
                        raise CommandError('El elemento del lote debe coincidir con un tipo de activo clasificado. Revisa el catálogo antes de importar.')
                    brand, _ = Brand.objects.get_or_create(name=stg.brand or 'Genérica')
                    model_obj, _ = ModelAsset.objects.get_or_create(name=stg.model or 'Genérico', brand=None, category=None)
                    
                    # 3. Creación del activo y generación de su código interno
                    asset = Asset.objects.create(
                        owner_company=owner,
                        legacy_asset_tag=stg.legacy_asset_tag,
                        serial_number=stg.serial_number,
                        category=cat,
                        model=model_obj,
                        brand=brand,
                        company=comp,
                        site=site,
                        observations=stg.observations
                    )
                    
                    # 4. Especificaciones técnicas y de red
                    AssetSpecs.objects.create(
                        asset=asset, ram=stg.ram, storage=stg.storage, 
                        processor=stg.processor, operating_system=stg.operating_system
                    )
                    
                    if stg.hostname or stg.mac_address:
                        AssetNetwork.objects.create(
                            asset=asset, hostname=stg.hostname, mac_address=stg.mac_address
                        )
                        
                    # 5. Actualizar el estado en Staging
                    stg.status = ImportStatus.IMPORTED
                    stg.save()
                    success_count += 1
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error fila {stg.row_number} (Placa {stg.legacy_asset_tag}): {e.__class__.__name__} - {str(e)}"))
                error_count += 1

        self.stdout.write(self.style.SUCCESS(f"Migración completada: {success_count} exitosos, {error_count} errores."))
