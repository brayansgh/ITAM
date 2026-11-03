from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from django.urls import reverse, path
from django.http import HttpResponseRedirect
from django.db.models import Count, Q
from .models import Assignment, AssignmentStatus, EmployeeAssetSummary
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
            modeladmin.message_user(request, f"Error: {e}", level=messages.ERROR)
    if generated > 0:
        modeladmin.message_user(request, f"Se generaron {generated} actas.", level=messages.SUCCESS)

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('asset', 'employee', 'assigned_by', 'assigned_at', 'status', 'download_pdf')
    list_filter = ('status', 'assigned_at', 'asset__company', 'asset__site')
    search_fields = ('asset__asset_tag', 'asset__serial_number', 'employee__full_name', 'employee__document_number')
    autocomplete_fields = ['asset', 'employee']
    date_hierarchy = 'assigned_at'
    actions = [generate_pdf_action]

    def get_form(self, request, obj=None, **kwargs):
        request.current_obj = obj
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "asset":
            if getattr(request, 'current_obj', None):
                kwargs["queryset"] = db_field.related_model.objects.filter(Q(status=AssetStatus.AVAILABLE) | Q(id=request.current_obj.asset_id))
            else:
                kwargs["queryset"] = db_field.related_model.objects.filter(status=AssetStatus.AVAILABLE)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change: obj.assigned_by = request.user
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
            url = reverse('download_act_pdf', args=[obj.id])
            return format_html('<a href="{}" target="_blank" style="background:#417690;color:white;padding:3px 8px;border-radius:3px;text-decoration:none;">Ver PDF</a>', url)
        return "-"

# NUEVA VISTA: Panel consolidado por Usuario
@admin.register(EmployeeAssetSummary)
class EmployeeAssetSummaryAdmin(admin.ModelAdmin):
    list_display = ('document_number', 'full_name', 'company', 'site', 'active_assets_count', 'generate_pdf_button')
    search_fields = ('document_number', 'full_name')
    list_filter = ('company', 'site')

    # Al ser una vista de reporte, bloqueamos la creación/edición manual de usuarios desde aquí
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Filtra solo los empleados que tengan al menos 1 asignación activa y cuenta cuántas tienen
        return qs.annotate(
            active_count=Count('assignments', filter=Q(assignments__status=AssignmentStatus.ACTIVE))
        ).filter(active_count__gt=0)

    @admin.display(description="Equipos Asignados", ordering='active_count')
    def active_assets_count(self, obj):
        return format_html('<span style="font-size:14px; font-weight:bold;">{}</span>', obj.active_count)

    @admin.display(description="Acción Directa")
    def generate_pdf_button(self, obj):
        url = reverse('admin:generate_summary_pdf', args=[obj.id])
        return format_html('<a href="{}" target="_blank" style="background:#28a745;color:white;padding:5px 10px;border-radius:4px;text-decoration:none;font-weight:bold;">Generar y Ver Acta</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/generate-pdf/', self.admin_site.admin_view(self.generate_employee_pdf_view), name='generate_summary_pdf'),
        ]
        return custom_urls + urls

    def generate_employee_pdf_view(self, request, object_id):
        emp = self.get_object(request, object_id)
        if not emp:
            self.message_user(request, "Usuario no encontrado.", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:assignments_employeeassetsummary_changelist'))
            
        first_active = emp.assignments.filter(status=AssignmentStatus.ACTIVE).first()
        if first_active:
            try:
                generate_act_pdf(first_active)
                first_active.save(update_fields=['signed_act_pdf'])
                return HttpResponseRedirect(reverse('download_act_pdf', args=[first_active.id]))
            except Exception as e:
                self.message_user(request, f"Error al generar PDF: {e}", level=messages.ERROR)
        return HttpResponseRedirect(reverse('admin:assignments_employeeassetsummary_changelist'))
