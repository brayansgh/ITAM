from inventory.navigation import AssetLinkAdminMixin
from core.admin_audit import StandardHistoryAdmin
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.models import Role
from inventory.models import AssetStatus

from .models import (
    Assignment,
    AssignmentStatus,
    EmployeeAssetSummary,
    OffboardingRecord,
    OffboardingRecordItem,
)
from .services import create_assignment
from .utils import generate_act_pdf


class AssignmentAdminForm(forms.ModelForm):

    class Meta:
        model = Assignment
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        # Estas validaciones solo aplican al crear asignaciones.
        if self.instance.pk:
            return cleaned_data

        asset = cleaned_data.get("asset")
        initial_condition = cleaned_data.get("initial_condition")

        if asset and asset.status != AssetStatus.AVAILABLE:
            self.add_error(
                "asset",
                "El activo seleccionado no está disponible.",
            )

        if not initial_condition or not initial_condition.strip():
            self.add_error(
                "initial_condition",
                "Debes registrar la condición inicial del activo.",
            )

        return cleaned_data


@admin.action(description="Generar/Regenerar Acta PDF para seleccionados")
def generate_pdf_action(modeladmin, request, queryset):
    generated = 0

    for obj in queryset:
        try:
            generate_act_pdf(obj)
            obj.save(update_fields=["signed_act_pdf"])
            generated += 1

        except Exception as e:
            modeladmin.message_user(
                request,
                f"Error: {e}",
                level=messages.ERROR,
            )

    if generated > 0:
        modeladmin.message_user(
            request,
            f"Se generaron {generated} actas.",
            level=messages.SUCCESS,
        )


@admin.register(Assignment)
class AssignmentAdmin(AssetLinkAdminMixin, StandardHistoryAdmin):

    exclude = ("signed_act_pdf",)

    list_display = (
        "asset",
        "employee",
        "assigned_by",
        "assigned_at",
        "status",
        "download_pdf",
    )

    list_filter = (
        "status",
        "assigned_at",
        "asset__company",
        "asset__site",
    )

    search_fields = (
        "asset__legacy_asset_tag",
        "asset__asset_tag",
        "asset__serial_number",
        "employee__full_name",
        "employee__document_number",
    )

    autocomplete_fields = ["asset", "employee"]
    date_hierarchy = "assigned_at"
    actions = [generate_pdf_action]
    form = AssignmentAdminForm

    def _user_has_role(self, request, *roles):
        user = request.user

        if not user.is_authenticated or not user.is_active or not user.is_staff:
            return False

        return user.is_superuser or user.role in roles

    def has_module_permission(self, request):
        return self._user_has_role(
            request,
            Role.ADMINISTRATOR,
            Role.TECHNOLOGY,
            Role.CONSULTATION,
        )

    def has_view_permission(self, request, obj=None):
        return self._user_has_role(
            request,
            Role.ADMINISTRATOR,
            Role.TECHNOLOGY,
            Role.CONSULTATION,
        )

    def has_add_permission(self, request):
        return self._user_has_role(
            request,
            Role.ADMINISTRATOR,
            Role.TECHNOLOGY,
        )

    def has_change_permission(self, request, obj=None):
        return self._user_has_role(
            request,
            Role.ADMINISTRATOR,
            Role.TECHNOLOGY,
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def get_form(self, request, obj=None, **kwargs):
        request.current_obj = obj
        return super().get_form(request, obj, **kwargs)

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs,
    ):
        if db_field.name == "asset":

            if getattr(request, "current_obj", None):
                kwargs["queryset"] = (
                    db_field.related_model.objects.filter(
                        Q(status=AssetStatus.AVAILABLE)
                        | Q(id=request.current_obj.asset_id)
                    )
                )
            else:
                kwargs["queryset"] = (
                    db_field.related_model.objects.filter(
                        status=AssetStatus.AVAILABLE
                    )
                )

        if db_field.name == "employee" and not getattr(request, "current_obj", None):
            from employees.models import EmployeeStatus
            kwargs["queryset"] = db_field.related_model.objects.exclude(status=EmployeeStatus.RETIRO)

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        assignment = create_assignment(
            asset_id=obj.asset_id,
            employee_id=obj.employee_id,
            assigned_by=request.user,
            initial_condition=obj.initial_condition,
        )

        obj.pk = assignment.pk
        obj._state.adding = False
        obj._state.db = assignment._state.db

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "asset",
                "employee",
                "assigned_by",
                "assigned_at",
                "returned_at",
                "initial_condition",
                "return_condition",
                "status",
                "observations",
                "download_pdf",
            )

        return (
            "assigned_by",
            "assigned_at",
            "returned_at",
            "return_condition",
            "status",
            "download_pdf",
        )

    @admin.display(description="Acta PDF")
    def download_pdf(self, obj):
        if obj.signed_act_pdf:
            url = reverse(
                "download_act_pdf",
                args=[obj.id],
            )

            return format_html(
                '<a href="{}" target="_blank" '
                'style="background:#417690;'
                'color:white;padding:3px 8px;'
                'border-radius:3px;'
                'text-decoration:none;">'
                "Ver PDF</a>",
                url,
            )

        return "-"


# NUEVA VISTA: Panel consolidado por Usuario
@admin.register(EmployeeAssetSummary)
class EmployeeAssetSummaryAdmin(StandardHistoryAdmin):
    def get_list_display(self, request):
        columns = super().get_list_display(request)
        if not (request.user.is_superuser or request.user.role in (Role.ADMINISTRATOR, Role.TECHNOLOGY)):
            return tuple(column for column in columns if column != 'generate_pdf_button')
        return columns

    list_display = (
        "document_number",
        "full_name",
        "company",
        "site",
        "active_assets_count",
        "generate_pdf_button",
    )

    search_fields = (
        "document_number",
        "full_name",
    )

    list_filter = (
        "company",
        "site",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        return (
            qs.annotate(
                active_count=Count(
                    "assignments",
                    filter=Q(
                        assignments__status=AssignmentStatus.ACTIVE
                    ),
                )
            ).filter(active_count__gt=0)
        )

    @admin.display(
        description="Equipos Asignados",
        ordering="active_count",
    )
    def active_assets_count(self, obj):
        return format_html(
            '<span style="font-size:14px; font-weight:bold;">{}</span>',
            obj.active_count,
        )

    @admin.display(description="Acción Directa")
    def generate_pdf_button(self, obj):
        url = reverse(
            "admin:generate_summary_pdf",
            args=[obj.id],
        )

        return format_html(
            '<a href="{}" target="_blank" '
            'style="background:#28a745;'
            'color:white;padding:5px 10px;'
            'border-radius:4px;'
            'text-decoration:none;'
            'font-weight:bold;">'
            "Generar y Ver Acta</a>",
            url,
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<path:object_id>/generate-pdf/",
                self.admin_site.admin_view(
                    self.generate_employee_pdf_view
                ),
                name="generate_summary_pdf",
            ),
        ]

        return custom_urls + urls

    def generate_employee_pdf_view(
        self,
        request,
        object_id,
    ):
               
        if not (
            self.has_view_permission(request)
            and request.user.is_active
            and request.user.is_staff
            and (
                request.user.is_superuser
                or request.user.role in (
                    Role.ADMINISTRATOR,
                    Role.TECHNOLOGY,
                )
            )
        ):
            raise PermissionDenied
        emp = self.get_object(request, object_id)

        if not emp:
            self.message_user(
                request,
                "Usuario no encontrado.",
                level=messages.ERROR,
            )

            return HttpResponseRedirect(
                reverse(
                    "admin:assignments_employeeassetsummary_changelist"
                )
            )

        first_active = emp.assignments.filter(
            status=AssignmentStatus.ACTIVE
        ).first()

        if first_active:
            try:
                generate_act_pdf(first_active)

                first_active.save(
                    update_fields=["signed_act_pdf"]
                )

                return HttpResponseRedirect(
                    reverse(
                        "download_act_pdf",
                        args=[first_active.id],
                    )
                )

            except Exception as e:
                self.message_user(
                    request,
                    f"Error al generar PDF: {e}",
                    level=messages.ERROR,
                )

        return HttpResponseRedirect(
            reverse(
                "admin:assignments_employeeassetsummary_changelist"
            )
        )


class OffboardingRecordItemInline(admin.TabularInline):

    model = OffboardingRecordItem
    extra = 0
    can_delete = False

    fields = (
        "assignment",
        "condition",
        "observations",
    )

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OffboardingRecord)
class OffboardingRecordAdmin(StandardHistoryAdmin):

    list_display = (
        "employee",
        "created_at",
        "received_by",
        "view_pdf",
    )

    search_fields = (
        "employee__full_name",
        "employee__document_number",
    )

    list_filter = (
        "created_at",
        "employee__company",
        "employee",
    )

    readonly_fields = (
        "employee",
        "received_by",
        "observations",
        "view_pdf",
        "created_at",
        "updated_at",
    )

    fields = (
        "employee",
        "received_by",
        "created_at",
        "observations",
        "view_pdf",
    )

    inlines = [OffboardingRecordItemInline]
    audit_related_models = ((OffboardingRecordItem, "offboarding_record"),)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Acta PDF")
    def view_pdf(self, obj):
        if not obj.pdf:
            return "PDF no disponible"

        url = reverse(
            "admin:assignments_offboardingrecord_view_pdf",
            args=[obj.pk],
        )

        return format_html(
            '<a class="button" href="{}" target="_blank">'
            "Ver / Descargar PDF</a>",
            url,
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<uuid:object_id>/view-pdf/",
                self.admin_site.admin_view(
                    self.view_pdf_view
                ),
                name="assignments_offboardingrecord_view_pdf",
            ),
        ]

        return custom_urls + urls

    def view_pdf_view(self, request, object_id):
        record = get_object_or_404(
            OffboardingRecord,
            pk=object_id,
        )

        if not self.has_view_permission(
            request,
            record,
        ):
            raise PermissionDenied

        if not record.pdf:
            messages.error(
                request,
                "Esta acta no tiene un PDF asociado.",
            )

            return redirect(
                "admin:assignments_offboardingrecord_changelist"
            )

        return FileResponse(
            record.pdf.open("rb"),
            content_type="application/pdf",
            filename=record.pdf.name.split("/")[-1],
            as_attachment=False,
        )
