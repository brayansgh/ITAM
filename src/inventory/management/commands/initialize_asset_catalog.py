from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import AssetGroup, Category

CATALOG = {
    AssetGroup.COMPUTING: ('Portátil', 'Escritorio', 'Servidor'),
    AssetGroup.PERIPHERALS: ('Monitor', 'Teclado', 'Mouse', 'Impresora', 'Escáner'),
    AssetGroup.NETWORK: ('Switch', 'Router', 'Punto de acceso', 'Firewall'),
    AssetGroup.TELEPHONY: ('Celular', 'Teléfono fijo', 'Teléfono IP', 'Radioteléfono'),
    AssetGroup.OTHER: ('UPS', 'Proyector', 'Otros equipos'),
}


class Command(BaseCommand):
    help = 'Crea los tipos acordados sin reclasificar categorías ni activos existentes.'

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for group, names in CATALOG.items():
            for name in names:
                if Category.objects.filter(name=name).exclude(group=group).exists():
                    name = f'{name} ({AssetGroup(group).label})'
                if not Category.objects.filter(name=name).exists():
                    category = Category(name=name, group=group)
                    category._change_reason = 'Catálogo inicial aprobado de grupo y tipo de activo'
                    category.save()
                    created += 1
        self.stdout.write(f'Tipos creados: {created}. Categorías existentes sin cambios.')
