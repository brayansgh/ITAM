from django.contrib import admin
from .models import StagingAsset, ImportStatus

@admin.action(description="Marcar seleccionados como APROBADOS")
def mark_approved(modeladmin, request, queryset):
    queryset.update(status=ImportStatus.APPROVED)

@admin.action(description="Marcar seleccionados como RECHAZADOS")
def mark_rejected(modeladmin, request, queryset):
    queryset.update(status=ImportStatus.REJECTED)

@admin.register(StagingAsset)
class StagingAssetAdmin(admin.ModelAdmin):
    list_display = ('sheet_name', 'row_number', 'legacy_asset_tag', 'element', 'employee_name', 'company', 'status')
    list_filter = ('status', 'sheet_name', 'company', 'site')
    search_fields = ('legacy_asset_tag', 'serial_number', 'employee_name', 'employee_document')
    actions = [mark_approved, mark_rejected]
    readonly_fields = ('sheet_name', 'row_number', 'validation_notes')
    list_editable = ('status',)
