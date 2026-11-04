from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from dataclasses import dataclass
from .models import MaintenanceRecord, MaintenanceDocument, MaintenanceStatus, MaintenanceType

@dataclass
class CustomChange:
    field: str
    old: str
    new: str

class MaintenanceDocumentInline(admin.TabularInline):
    model = MaintenanceDocument
    extra = 1
    max_num = 3

@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(SimpleHistoryAdmin):
    list_display = ('asset', 'type', 'status', 'reported_by')
    list_filter = ('type', 'status')
    search_fields = ('asset__asset_tag', 'description', 'provider')
    inlines = [MaintenanceDocumentInline]

    def history_view(self, request, object_id, extra_context=None):
        response = super().history_view(request, object_id, extra_context=extra_context)
        
        if hasattr(response, 'context_data') and 'action_list' in response.context_data:
            STATUS_MAP = dict(MaintenanceStatus.choices)
            TYPE_MAP = dict(MaintenanceType.choices)
            
            FIELD_MAP = {
                'status': 'Estado del Ticket',
                'type': 'Tipo de Evento',
                'description': 'Descripción',
                'provider': 'Proveedor',
                'cost': 'Costo',
                'resolution_notes': 'Notas de Resolución',
            }

            for action in response.context_data['action_list']:
                if hasattr(action, 'delta') and action.delta:
                    translated_changes = []
                    for change in action.delta.changes:
                        field_label = FIELD_MAP.get(change.field, change.field)
                        old_val = change.old
                        new_val = change.new
                        
                        if change.field == 'status':
                            old_val = STATUS_MAP.get(old_val, old_val)
                            new_val = STATUS_MAP.get(new_val, new_val)
                        elif change.field == 'type':
                            old_val = TYPE_MAP.get(old_val, old_val)
                            new_val = TYPE_MAP.get(new_val, new_val)
                            
                        translated_changes.append(CustomChange(field=field_label, old=old_val, new=new_val))
                    
                    action.delta.changes = translated_changes
        return response
