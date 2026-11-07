from inventory.navigation import AssetLinkAdminMixin
from core.admin_audit import StandardHistoryAdmin
from django import forms
from django.forms.models import BaseInlineFormSet
from django.core.exceptions import ValidationError
from django.contrib import admin
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
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


def closing_decommission(ticket):
    return ticket.type == MaintenanceType.DECOMMISSION and ticket.status == MaintenanceStatus.COMPLETED


class MaintenanceDocumentFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if (self.instance.status in CLOSED_STATUSES
                and not closing_decommission(self.instance)
                and any(form.has_changed() for form in self.forms)):
            raise ValidationError("Guarda los documentos antes de cerrar el ticket; sus evidencias quedan bloqueadas al cierre.")


class MaintenanceTicketForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.status_before_form = self.instance.status

    def clean(self):
        data = super().clean()
        if (data.get("type") == MaintenanceType.DECOMMISSION
                and data.get("status") == MaintenanceStatus.COMPLETED
                and not data.get("decommission_reason")):
            self.add_error("decommission_reason", "Selecciona el motivo de la baja antes de completarla.")
        return data


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

    def documents_readonly(self, obj):
        return obj is not None and (
            getattr(obj, "status_before_form", obj.status) in CLOSED_STATUSES
            or obj.asset.status == "DECOMMISSIONED"
        )

    def get_fields(self, request, obj=None):
        if self.documents_readonly(obj):
            return ("protected_document",)
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if self.documents_readonly(obj):
            return ("protected_document",)
        return ()

    def has_add_permission(self, request, obj=None):
        return not (self.documents_readonly(obj)) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (self.documents_readonly(obj)) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (self.documents_readonly(obj)) and super().has_delete_permission(request, obj)

@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(AssetLinkAdminMixin, StandardHistoryAdmin):
    list_per_page = 25
    form = MaintenanceTicketForm
    change_form_template = 'admin/maintenance/ticket_form.html'
    list_display = ('ticket_reference', 'asset', 'type', 'status', 'reported_by')
    list_display_links = ('ticket_reference',)
    list_filter = ('type', 'status')
    search_fields = ('asset__legacy_asset_tag', 'asset__asset_tag', 'description', 'provider')
    fieldsets = (
        ('Información del ticket', {'fields': ('asset', 'type', 'description', 'reported_by', 'provider', 'cost')}),
        ('Resolución y estado', {'fields': ('resolution_notes', 'status'), 'description': 'Guarda las evidencias antes de cerrar. Los tickets cerrados quedan de solo consulta.'}),
    )
    inlines = [MaintenanceDocumentInline]
    audit_related_models = ((MaintenanceDocument, "maintenance"),)

    def is_decommission_form(self, request, obj=None):
        if obj is not None:
            return obj.type == MaintenanceType.DECOMMISSION
        route = getattr(getattr(request, "resolver_match", None), "url_name", "")
        return route == "maintenance_decommission_add" or request.GET.get("type") == MaintenanceType.DECOMMISSION

    def get_fieldsets(self, request, obj=None):
        if self.is_decommission_form(request, obj):
            return (
                ("Trámite de baja", {"fields": ("asset", "type", "decommission_reason", "description", "reported_by")}),
                ("Resolución de baja", {"fields": ("resolution_notes", "status")}),
            )
        return super().get_fieldsets(request, obj)

    def decommission_change_view(self, request, object_id):
        get_object_or_404(self.get_queryset(request), pk=object_id, type=MaintenanceType.DECOMMISSION)
        return self.change_view(request, str(object_id))

    def response_add(self, request, obj, post_url_continue=None):
        if obj.type == MaintenanceType.DECOMMISSION and "_save" in request.POST and "_popup" not in request.POST:
            return self.response_decommission_saved(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if obj.type == MaintenanceType.DECOMMISSION and "_save" in request.POST and "_popup" not in request.POST:
            return self.response_decommission_saved(request, obj)
        return super().response_change(request, obj)

    def response_decommission_saved(self, request, obj):
        self.message_user(request, "Trámite de baja guardado.")
        if obj.status == MaintenanceStatus.CANCELLED:
            return redirect(reverse("admin:itam_decommissions") + "?estado=cancelados")
        if obj.status == MaintenanceStatus.COMPLETED:
            return redirect(reverse("admin:itam_decommissions") + "?estado=definitivas")
        return redirect(reverse("admin:maintenance_decommission_change", args=[obj.pk]))

    def can_manage_return_links(self, request):
        return self.has_module_permission(request) and (
            self.has_add_permission(request) or self.has_change_permission(request)
        )

    def can_link_return(self, request, ticket):
        if not self.has_module_permission(request):
            return False
        if ticket is None:
            return self.has_add_permission(request)
        return self.has_view_permission(request, ticket) and self.has_change_permission(request, ticket)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if self.is_decommission_form(request, obj):
            context.update(
                is_decommission=True,
                title="Iniciar trámite de baja" if add else "Trámite de baja",
                itam_cancel_url=reverse("admin:itam_decommissions"),
            )
        elif obj and self.has_module_permission(request) and self.has_add_permission(request):
            context["start_decommission_url"] = reverse("admin:maintenance_decommission_add") + f"?asset={obj.asset_id}"
        if obj and obj.return_item_id:
            from assignments.models import OffboardingRecord

            record = obj.return_item.offboarding_record
            returns_admin = self.admin_site._registry[OffboardingRecord]
            if returns_admin.has_module_permission(request) and returns_admin.has_view_permission(request, record):
                context["return_record_url"] = reverse("admin:assignments_offboardingrecord_change", args=[record.pk])
        return super().render_change_form(request, context, add, change, form_url, obj)

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {**(extra_context or {}), "title": "Mantenimiento"})

    def save_model(self, request, obj, form, change):
        if closing_decommission(obj):
            # Admin mantiene la transacción abierta hasta guardar los anexos y cerrar la baja.
            from django.db import router
            from inventory.models import Asset
            from .closure import validate_ticket

            using = router.db_for_write(self.model)
            asset = Asset.objects.using(using).select_for_update().get(pk=obj.asset_id)
            previous = self.model.objects.using(using).filter(pk=obj.pk).first()
            validate_ticket(obj, using, previous, asset)
            if not change:
                obj.status = MaintenanceStatus.OPEN
                super().save_model(request, obj, form, change)
                obj.status = MaintenanceStatus.COMPLETED
            return
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if closing_decommission(form.instance):
            form.instance.save()

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        match = getattr(request, 'resolver_match', None)
        if match and match.url_name == 'maintenance_maintenancerecord_changelist':
            qs = qs.exclude(type=MaintenanceType.DECOMMISSION)
        return qs

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
            form.base_fields["status"].help_text = (
                "Al completar la baja, el trámite y sus anexos quedarán de solo consulta."
                if self.is_decommission_form(request, obj)
                else "Guarda las evidencias antes de cerrar. Los tickets completados o cancelados serán de solo consulta."
            )
        if "type" in form.base_fields:
            type_field = form.base_fields["type"]
            if self.is_decommission_form(request, obj):
                type_field.initial = MaintenanceType.DECOMMISSION
                type_field.disabled = True
            else:
                type_field.choices = [(key, label) for key, label in MaintenanceType.choices
                                      if key != MaintenanceType.DECOMMISSION]
        return form

    def has_change_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status_before_form", obj.status) in CLOSED_STATUSES:
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
