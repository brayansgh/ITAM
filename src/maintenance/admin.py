from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from simple_history.admin import SimpleHistoryAdmin
from dataclasses import dataclass
from .models import MaintenanceRecord, MaintenanceDocument, MaintenanceStatus, MaintenanceType

@dataclass
class CustomChange:
    field: str
    old: str
    new: str

class PrivateDocumentWidget(AdminFileWidget):
    template_name = "admin/maintenance/private_file_input.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if value and value.instance.pk:
            context["widget"]["download_url"] = reverse(
                "admin:maintenance_document_download", args=[value.instance.pk]
            )
        return context


class MaintenanceDocumentForm(forms.ModelForm):
    class Meta:
        model = MaintenanceDocument
        fields = "__all__"
        widgets = {"document": PrivateDocumentWidget}


class MaintenanceDocumentInline(admin.TabularInline):
    model = MaintenanceDocument
    form = MaintenanceDocumentForm
    extra = 1
    max_num = 3

@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(SimpleHistoryAdmin):
    list_display = ('asset', 'type', 'status', 'reported_by')
    list_filter = ('type', 'status')
    search_fields = ('asset__asset_tag', 'description', 'provider')
    inlines = [MaintenanceDocumentInline]

    def get_urls(self):
        return [
            path(
                "documents/<int:document_id>/download/",
                self.admin_site.admin_view(self.download_document),
                name="maintenance_document_download",
            ),
        ] + super().get_urls()

    def download_document(self, request, document_id):
        document = get_object_or_404(
            MaintenanceDocument.objects.select_related("maintenance"), pk=document_id
        )
        if not self.has_view_permission(request, document.maintenance):
            raise PermissionDenied
        if not document.document:
            raise Http404("Documento no disponible")
        return FileResponse(document.document.open("rb"), content_type="application/pdf")

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
