import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from inventory.models import Asset
from .models import MaintenanceRecord, MaintenanceType, MaintenanceStatus

@receiver(post_save, sender=Asset)
def auto_create_maintenance_ticket(sender, instance, **kwargs):
    print(f"--- [DIAGNÓSTICO] SEÑAL DISPARADA PARA: {instance.asset_tag} | ESTADO: {instance.status} ---")
    
    # Validamos de forma flexible (mayúsculas e inclusión de palabra)
    if "MAINTENANCE" in str(instance.status).upper():
        active_ticket = MaintenanceRecord.objects.filter(
            asset=instance,
            status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS]
        ).exists()
        
        print(f"--- [DIAGNÓSTICO] TICKET ACTIVO EXISTENTE: {active_ticket} ---")
        
        if not active_ticket:
            User = get_user_model()
            # Intenta buscar un superusuario, si no encuentra, toma el primer usuario del sistema
            sys_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
            
            if sys_user:
                MaintenanceRecord.objects.create(
                    asset=instance,
                    type=MaintenanceType.CORRECTIVE,
                    status=MaintenanceStatus.OPEN,
                    description="Ticket autogenerado: El estado del activo fue cambiado a Mantenimiento desde el inventario.",
                    reported_by=sys_user
                )
                print("--- [DIAGNÓSTICO] TICKET CREADO CON ÉXITO ---")
            else:
                print("--- [DIAGNÓSTICO] ERROR: NO HAY USUARIOS PARA ASIGNAR ---")
