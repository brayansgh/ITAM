from django.contrib import admin
from django.contrib import messages
from .models import MaintenanceRecord, MaintenanceType, MaintenanceStatus

@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ('asset', 'type', 'status', 'reported_by', 'cost', 'created_at')
    list_filter = ('type', 'status', 'created_at')
    search_fields = ('asset__asset_tag', 'asset__serial_number', 'provider', 'description')
    autocomplete_fields = ['asset']
    readonly_fields = ('reported_by',)
    fieldsets = (
        ('Información del Activo', {'fields': ('asset', 'type', 'status', 'description')}),
        ('Gestión y Costos', {'fields': ('provider', 'cost', 'resolution_notes', 'support_document')}),
        ('Auditoría', {'fields': ('reported_by',)}),
    )

    def save_model(self, request, obj, form, change):
        # Auto-asignar el usuario logueado como el gestor del ticket
        if not change:
            obj.reported_by = request.user
        super().save_model(request, obj, form, change)

        # Lógica de sincronización ISO 27001 con el inventario principal
        try:
            if obj.status in [MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS]:
                if obj.type == MaintenanceType.DECOMMISSION:
                    obj.asset.status = 'DECOMMISSIONED'
                else:
                    obj.asset.status = 'IN_MAINTENANCE'
            elif obj.status == MaintenanceStatus.COMPLETED:
                if obj.type != MaintenanceType.DECOMMISSION:
                    obj.asset.status = 'AVAILABLE' # Si se repara, vuelve a estar disponible
            obj.asset.save()
        except Exception as e:
            messages.warning(request, f"Registro guardado, pero hubo un problema al actualizar el estado del activo: {e}")
