from core.admin_audit import StandardHistoryAdmin
from django.contrib import admin
from .models import StagingAsset, ImportStatus
from django.db import transaction
@admin.action(description="Marcar seleccionados como APROBADOS")
def mark_approved(modeladmin, request, queryset):
    set_import_status(queryset, ImportStatus.APPROVED, request.user)

@admin.action(description="Marcar seleccionados como RECHAZADOS")
def mark_rejected(modeladmin, request, queryset):
    set_import_status(queryset, ImportStatus.REJECTED, request.user)

@admin.register(StagingAsset)
class StagingAssetAdmin(StandardHistoryAdmin):
    list_display = ('sheet_name', 'row_number', 'legacy_asset_tag', 'element', 'employee_name', 'company', 'status')
    list_filter = ('status', 'sheet_name', 'company', 'site')
    search_fields = ('legacy_asset_tag', 'serial_number', 'employee_name', 'employee_document')
    actions = [mark_approved, mark_rejected]
    readonly_fields = ('sheet_name', 'row_number', 'validation_notes')
    list_editable = ('status',)


@transaction.atomic
def set_import_status(queryset, status, actor):
    for item in queryset.select_for_update().iterator():
        if item.status == status:
            continue
        item.status = status
        item._history_user = actor
        item.save(update_fields=["status", "updated_at"])
