from inventory.navigation import AssetLinkAdminMixin
from core.admin_audit import StandardHistoryAdmin
from django import forms
from django.forms.models import BaseInlineFormSet
from django.core.exceptions import ValidationError
from django.contrib import admin
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from .models import MaintenanceRecord, MaintenanceDocument, MaintenanceStatus, MaintenanceType
from .closure import CLOSED_STATUSES

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


class MaintenanceDocumentFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if self.instance.status in CLOSED_STATUSES and any(form.has_changed() for form in self.forms):
            raise ValidationError("Guarda los documentos antes de cerrar el ticket; sus evidencias quedan bloqueadas al cierre.")


class MaintenanceDocumentInline(admin.TabularInline):
    model = MaintenanceDocument
    form = MaintenanceDocumentForm
    formset = MaintenanceDocumentFormSet
    extra = 1
    max_num = 3

    @admin.display(description="Documento")
    def protected_document(self, obj):
        if not obj.pk or not obj.document:
            return "Sin documento"
        return format_html('<a href="{}">Ver / Descargar documento</a>', reverse(
            "admin:maintenance_document_download", args=[obj.pk],
        ))

    def get_fields(self, request, obj=None):
        if obj and (obj.status in CLOSED_STATUSES or obj.asset.status == "DECOMMISSIONED"):
            return ("protected_document",)
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj and (obj.status in CLOSED_STATUSES or obj.asset.status == "DECOMMISSIONED"):
            return ("protected_document",)
        return ()

    def has_add_permission(self, request, obj=None):
        return not (obj and (obj.status in CLOSED_STATUSES or obj.asset.status == "DECOMMISSIONED")) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and (obj.status in CLOSED_STATUSES or obj.asset.status == "DECOMMISSIONED")) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.status in CLOSED_STATUSES or obj.asset.status == "DECOMMISSIONED")) and super().has_delete_permission(request, obj)

@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(AssetLinkAdminMixin, StandardHistoryAdmin):
    list_display = ('ticket_reference', 'asset', 'type', 'status', 'reported_by')
    list_display_links = ('ticket_reference',)
    list_filter = ('type', 'status')
    search_fields = ('asset__asset_tag', 'description', 'provider')
    inlines = [MaintenanceDocumentInline]
    audit_related_models = ((MaintenanceDocument, "maintenance"),)

    @admin.display(description="Ticket", ordering="created_at")
    def ticket_reference(self, obj):
        return "Ticket " + str(obj.pk)[:8].upper()

    def get_list_display(self, request):
        columns = super().get_list_display(request)

        @admin.display(description="Gestión")
        def ticket_management(obj):
            if not self.has_view_permission(request, obj):
                return "Sin permiso"
            label = "Gestionar ticket" if self.has_change_permission(request, obj) else "Ver ticket"
            return format_html('<a class="button" href="{}">{}</a>', reverse(
                "admin:maintenance_maintenancerecord_change", args=[obj.pk],
            ), label)

        return (*columns, ticket_management)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "status" in form.base_fields:
            form.base_fields["status"].help_text = "Guarda las evidencias antes de cerrar. Los tickets completados o cancelados serán de solo consulta."
        return form

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status in CLOSED_STATUSES:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in CLOSED_STATUSES:
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

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
