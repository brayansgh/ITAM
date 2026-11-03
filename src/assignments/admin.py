from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django.urls import reverse
from .models import Assignment, AssignmentStatus
from inventory.models import AssetStatus
from .utils import generate_act_pdf

@admin.action(description="Generar/Regenerar Acta PDF para seleccionados")
def generate_pdf_action(modeladmin, request, queryset):
    generated = 0
    for obj in queryset:
        try:
            generate_act_pdf(obj)
            obj.save(update_fields=['signed_act_pdf'])
            generated += 1
        except Exception as e:
            modeladmin.message_user(request, f"Error generando PDF para {obj}: {e}", level=messages.ERROR)
    
    if generated > 0:
        modeladmin.message_user(request, f"Se generaron {generated} actas en PDF exitosamente.", level=messages.SUCCESS)

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('asset', 'employee', 'assigned_by', 'assigned_at', 'status', 'download_pdf')
    list_filter = ('status', 'assigned_at', 'asset__company', 'asset__site')
    search_fields = (
        'asset__asset_tag', 'asset__legacy_asset_tag', 'asset__serial_number',
        'employee__full_name', 'employee__document_number'
    )
    autocomplete_fields = ['asset', 'employee']
    date_hierarchy = 'assigned_at'
    actions = [generate_pdf_action]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.assigned_by = request.user
            
        super().save_model(request, obj, form, change)
        
        if obj.status == AssignmentStatus.ACTIVE:
            obj.asset.status = AssetStatus.ASSIGNED
            obj.asset.save()
        elif obj.status == AssignmentStatus.RETURNED:
            obj.asset.status = AssetStatus.AVAILABLE
            obj.asset.save()

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == AssignmentStatus.RETURNED:
            return ('asset', 'employee', 'assigned_by', 'assigned_at', 'returned_at', 'initial_condition', 'status', 'signed_act_pdf')
        return ('assigned_by', 'assigned_at', 'signed_act_pdf')

    @admin.display(description="Acta PDF")
    def download_pdf(self, obj):
        if obj.signed_act_pdf:
            # Enlaza a la URL segura en lugar de la pública
            url = reverse('download_act_pdf', args=[obj.id])
            return format_html('<a href="{}" target="_blank" style="background:#417690;color:white;padding:3px 8px;border-radius:3px;text-decoration:none;">Ver PDF</a>', url)
        return "-"
