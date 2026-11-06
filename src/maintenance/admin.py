from inventory.navigation import AssetLinkAdminMixin
from core.admin_audit import StandardHistoryAdmin
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from .models import MaintenanceRecord, MaintenanceDocument, MaintenanceStatus, MaintenanceType

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
class MaintenanceRecordAdmin(AssetLinkAdminMixin, StandardHistoryAdmin):
    list_display = ('asset', 'type', 'status', 'reported_by')
    list_filter = ('type', 'status')
    search_fields = ('asset__asset_tag', 'description', 'provider')
    inlines = [MaintenanceDocumentInline]
    audit_related_models = ((MaintenanceDocument, "maintenance"),)

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
