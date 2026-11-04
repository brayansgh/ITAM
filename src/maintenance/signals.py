import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from inventory.models import Asset
from .models import MaintenanceRecord, MaintenanceType, MaintenanceStatus

# 1. Regla Global de Desvinculación (Antes de guardar el Activo)
@receiver(pre_save, sender=Asset)
def enforce_unassignment_on_unavailable(sender, instance, **kwargs):
    status_str = str(getattr(instance, "status", "")).upper()
    
    # Si el activo entra a Baja o Mantenimiento, pierde la asignación
    if "DECOMMISSION" in status_str or "MAINTENANCE" in status_str:
        # A. Limpiar campos de asignación directa
        for field in ['assigned_to', 'employee', 'user', 'assigned_user']:
            if hasattr(instance, field) and getattr(instance, field) is not None:
                setattr(instance, field, None)

# 2. Sincronización de Inventario -> Mantenimiento y Cierre de Asignaciones
@receiver(post_save, sender=Asset)
def sync_inventory_to_maintenance(sender, instance, **kwargs):
    status_str = str(getattr(instance, "status", "")).upper()
    User = get_user_model()
    sys_user = getattr(instance, '_history_user', None) or User.objects.filter(is_superuser=True).first() or User.objects.first()

    # A. Buscador dinámico para cerrar registros en el "Apartado de Asignaciones"
    if "DECOMMISSION" in status_str or "MAINTENANCE" in status_str:
        for related_object in instance._meta.related_objects:
            accessor_name = related_object.get_accessor_name()
            if accessor_name and any(kw in accessor_name.lower() for kw in ['assign', 'asignacion']):
                manager = getattr(instance, accessor_name, None)
                if manager:
                    for assignment in manager.all():
                        changed = False
                        
                        # Apagar booleanos de estado activo
                        for bool_field in ['is_active', 'active', 'is_assigned']:
                            if hasattr(assignment, bool_field) and getattr(assignment, bool_field):
                                setattr(assignment, bool_field, False)
                                changed = True
                                
                        # Registrar fecha de devolución
                        for date_field in ['return_date', 'fecha_devolucion', 'end_date']:
                            if hasattr(assignment, date_field) and not getattr(assignment, date_field):
                                setattr(assignment, date_field, timezone.now().date())
                                changed = True
                                
                        # Cambiar estados de texto
                        for status_field in ['status', 'estado']:
                            if hasattr(assignment, status_field):
                                val = str(getattr(assignment, status_field)).upper()
                                if val in ['ACTIVE', 'ACTIVO', 'ASSIGNED', 'ASIGNADO']:
                                    setattr(assignment, status_field, 'RETURNED')
                                    changed = True

                        if changed:
                            try:
                                if hasattr(assignment, '_change_reason'):
                                    assignment._change_reason = "Cerrado automático: Activo en Baja/Mantenimiento"
                                assignment.save()
                            except Exception:
                                pass

    # B. Creación automática de tickets
    if "MAINTENANCE" in status_str:
        active_ticket = MaintenanceRecord.objects.filter(
            asset=instance, status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS]
        ).exclude(type=MaintenanceType.DECOMMISSION).exists()
        
        if not active_ticket and sys_user:
            ticket = MaintenanceRecord(
                asset=instance, type=MaintenanceType.CORRECTIVE, status=MaintenanceStatus.OPEN,
                description="Ticket autogenerado: El activo fue cambiado a estado Mantenimiento.",
                reported_by=sys_user
            )
            ticket._history_user = sys_user
            ticket.save()
            
    elif "DECOMMISSION" in status_str:
        decom_ticket = MaintenanceRecord.objects.filter(asset=instance, type=MaintenanceType.DECOMMISSION).exists()
        if not decom_ticket and sys_user:
            ticket = MaintenanceRecord(
                asset=instance, type=MaintenanceType.DECOMMISSION, status=MaintenanceStatus.OPEN,
                description="Ticket autogenerado: El activo fue marcado como Baja desde el inventario.",
                reported_by=sys_user
            )
            ticket._history_user = sys_user
            ticket.save()

# 3. Sincronización de Mantenimiento -> Inventario
@receiver(post_save, sender=MaintenanceRecord)
def sync_maintenance_to_inventory(sender, instance, **kwargs):
    current_asset_status = getattr(instance.asset, "status", "")
    new_asset_status = current_asset_status
    reason = ""

    if instance.type == MaintenanceType.DECOMMISSION:
        new_asset_status = "DECOMMISSIONED"
        reason = f"Sincronizado: Baja definitiva procesada en Mantenimientos ({instance.get_status_display()})"
    elif instance.status in [MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS]:
        new_asset_status = "IN_MAINTENANCE"
        reason = f"Sincronizado: Ticket de mantenimiento activo ({instance.get_type_display()})"
    elif instance.status in [MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED]:
        new_asset_status = "AVAILABLE"
        reason = f"Sincronizado: Liberado por cierre de ticket ({instance.get_status_display()})"

    if new_asset_status != current_asset_status:
        instance.asset.status = new_asset_status
        instance.asset._change_reason = reason
        
        user = getattr(instance, 'history_user', None) or getattr(instance, 'reported_by', None)
        if user:
            instance.asset._history_user = user
            
        # Al ejecutar save(), el pre_save del Asset limpiará la asignación automáticamente
        instance.asset.save()
