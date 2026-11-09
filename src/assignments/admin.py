from inventory.navigation import AssetLinkAdminMixin, asset_link
from core.admin_audit import StandardHistoryAdmin
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from accounts.models import Role
from inventory.models import AssetStatus

from .models import (
    Assignment,
    AssignmentStatus,
    EmployeeAssetSummary,
    OffboardingRecord,
    OffboardingRecordItem,
)
from .services import create_assignment, link_return_to_decommission
from .utils import AssignmentActError, issue_assignment_act


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
            issue_assignment_act(obj.pk, actor=request.user)
            generated += 1

        except AssignmentActError:
            modeladmin.message_user(
                request,
                "No se pudo generar el acta.",
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

    def get_urls(self):
        return [
            path("<uuid:assignment_id>/acta/", self.admin_site.admin_view(self.act_view),
                 name="assignments_assignment_act"),
        ] + super().get_urls()

    def response_add(self, request, obj, post_url_continue=None):
        if IS_POPUP_VAR in request.POST:
            return super().response_add(request, obj, post_url_continue)
        url = reverse("admin:assignments_assignment_act", args=[obj.pk])
        return HttpResponseRedirect(url + "?confirmada=1")

    def act_view(self, request, assignment_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        assignment = get_object_or_404(
            self.get_queryset(request).select_related("asset", "employee"), pk=assignment_id,
        )
        can_generate = self.can_generate_delivery_act(request, assignment)
        if request.method == "POST":
            if not can_generate:
                raise PermissionDenied
            mode = request.POST.get("mode")
            if mode not in ("delivery", "consolidated"):
                return HttpResponseBadRequest("Selecciona una modalidad de acta válida.")
            try:
                issue_assignment_act(assignment.pk, actor=request.user, include_active_custody=mode == "consolidated")
            except AssignmentActError as error:
                message = str(error) or "No se pudo generar el acta."
                self.message_user(request, f"{message} La asignación sigue registrada.", messages.ERROR)
            else:
                self.message_user(request, "Acta PDF generada.", messages.SUCCESS)
            return redirect("admin:assignments_assignment_act", assignment_id=assignment.pk)

        previous_acts = (
            assignment.history.exclude(signed_act_pdf__isnull=True)
            .exclude(signed_act_pdf__in=["", assignment.signed_act_pdf.name or ""])
            .order_by("signed_act_pdf", "history_date", "history_id").distinct("signed_act_pdf")
            .values("history_date", "history_id", "history_change_reason")
        )
        return render(request, "assignments/act_confirmation.html", {
            **self.admin_site.each_context(request),
            "title": "Actas de asignación",
            "assignment": assignment,
            "delivery_assets": [asset_link(request, assignment.asset, self.admin_site)],
            "show_selector": can_generate and request.GET.get("confirmada") == "1",
            "can_generate": can_generate,
            "return_pdf_url": self.return_pdf_url(request, assignment),
            "previous_acts": sorted(previous_acts, key=lambda entry: entry["history_date"], reverse=True),
        })

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("offboarding_item__offboarding_record")

    def get_list_display(self, request):
        return tuple(self.pdf_column(request) if field == "download_pdf" else field
                     for field in super().get_list_display(request))

    def pdf_column(self, request):
        if hasattr(request, "_itam_assignment_pdf_column"):
            return request._itam_assignment_pdf_column

        @admin.display(description="Acta PDF")
        def documents(obj):
            return self.download_pdf(obj, request)
        request._itam_assignment_pdf_column = documents
        return documents

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
                self.pdf_column(request),
            )

        return (
            "assigned_by",
            "assigned_at",
            "returned_at",
            "return_condition",
            "status",
            "download_pdf",
        )

    def can_generate_delivery_act(self, request, assignment):
        return (
            assignment.status == AssignmentStatus.ACTIVE and assignment.returned_at is None
            and self.has_add_permission(request)
        )

    def return_pdf_url(self, request, assignment):
        item = getattr(assignment, "offboarding_item", None)
        if item and item.offboarding_record.pdf:
            record_admin = self.admin_site.get_model_admin(OffboardingRecord)
            if record_admin.can_view_receipt(request, item.offboarding_record):
                return reverse("admin:assignments_offboardingrecord_view_pdf", args=[item.offboarding_record_id])
        return None

    @admin.display(description="Acta PDF")
    def download_pdf(self, obj, request=None):
        if not obj:
            return "—"
        if request is None:
            if obj.signed_act_pdf:
                return format_html('<a href="{}">Acta de entrega</a>', reverse("download_act_pdf", args=[obj.pk]))
            return "—"
        links = []
        return_url = self.return_pdf_url(request, obj)
        if return_url:
            links.append((return_url, "Acta de devolución"))
        if self.can_generate_delivery_act(request, obj):
            links.append((
                reverse("admin:assignments_assignment_act", args=[obj.pk]), "Gestionar acta",
            ))
        elif obj.signed_act_pdf:
            links.append((
                reverse("admin:assignments_assignment_act", args=[obj.pk]), "Acta de entrega",
            ))
        if not links:
            return "—"
        actions = format_html_join(
            "", '<a class="itam-table-action" href="{}" target="_blank" rel="noopener">{}</a>', links,
        )
        return format_html('<div class="itam-table-actions">{}</div>', actions)



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
            '<span class="itam-label">{}</span>',
            obj.active_count,
        )

    @admin.display(description="Acción Directa")
    def generate_pdf_button(self, obj):
        url = reverse(
            "admin:generate_summary_pdf",
            args=[obj.id],
        )

        return format_html(
            '<a class="itam-table-action" href="{}" target="_blank" rel="noopener">Generar y ver acta</a>',
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
                issue_assignment_act(first_active.pk, actor=request.user, include_active_custody=True)

                return HttpResponseRedirect(
                    reverse(
                        "download_act_pdf",
                        args=[first_active.id],
                    )
                )

            except AssignmentActError:
                self.message_user(
                    request,
                    "No se pudo generar el acta.",
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
        "received_asset",
        "condition",
        "observations",
    )

    readonly_fields = fields

    @admin.display(description="Activo recibido")
    def received_asset(self, obj):
        return obj.assignment.asset if obj else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("assignment__asset")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OffboardingRecord)
class OffboardingRecordAdmin(StandardHistoryAdmin):
    change_form_template = "admin/assignments/offboardingrecord/change_form.html"

    list_display = (
        "employee",
        "receipt_date",
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
        "return_reason",
        "observations",
        "view_pdf",
        "receipt_date",
        "updated_at",
    )

    fields = (
        "employee",
        "received_by",
        "receipt_date",
        "return_reason",
        "observations",
        "view_pdf",
    )

    inlines = [OffboardingRecordItemInline]
    audit_related_models = ((OffboardingRecordItem, "offboarding_record"),)

    @admin.display(description="Fecha de registro", ordering="created_at")
    def receipt_date(self, obj):
        return obj.created_at

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
            '<a class="itam-table-action" href="{}" target="_blank" rel="noopener">'
            "Ver / Descargar PDF</a>",
            url,
        )

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj and obj.return_reason:
            from maintenance.models import MaintenanceRecord

            maintenance_admin = self.admin_site._registry[MaintenanceRecord]
            entries = []
            for item in obj.items.select_related("assignment__asset").prefetch_related("decommission_tickets"):
                tickets = []
                if maintenance_admin.has_module_permission(request):
                    tickets = [
                        {"label": ticket.get_status_display(),
                         "url": reverse("admin:maintenance_decommission_change", args=[ticket.pk])}
                        for ticket in item.decommission_tickets.all()
                        if maintenance_admin.has_view_permission(request, ticket)
                    ]
                start_url = None
                if (maintenance_admin.can_manage_return_links(request)
                        and item.assignment.asset.status != AssetStatus.DECOMMISSIONED):
                    start_url = reverse("admin:assignments_offboardingrecord_link_decommission",
                                        args=[obj.pk, item.pk])
                entries.append({"asset": item.assignment.asset, "tickets": tickets, "start_url": start_url})
            context["return_decommission_entries"] = entries
        return super().render_change_form(request, context, add, change, form_url, obj)

    def link_decommission_view(self, request, object_id, item_id):
        from django.http import HttpResponseNotAllowed
        from maintenance.models import MaintenanceRecord

        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        record = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not (self.has_module_permission(request) and self.has_view_permission(request, record)):
            raise PermissionDenied
        item = get_object_or_404(record.items.select_related("assignment", "offboarding_record"), pk=item_id)
        maintenance_admin = self.admin_site._registry[MaintenanceRecord]

        def authorize(ticket):
            if not maintenance_admin.can_link_return(request, ticket):
                raise PermissionDenied

        try:
            link_return_to_decommission(item=item, actor=request.user, authorize=authorize)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Trámite de baja vinculado al activo y a su acta de devolución.")
        return redirect(reverse("admin:assignments_offboardingrecord_change", args=[record.pk]))

    def can_view_receipt(self, request, record):
        if self.has_view_permission(request, record):
            return True
        from employees.models import Employee
        employee_admin = self.admin_site._registry[Employee]
        return (record.received_by_id == request.user.pk
                and employee_admin.can_process_offboarding(request, record.employee))

    def receipt_view(self, request, object_id):
        record = get_object_or_404(self.get_queryset(request).select_related("employee", "received_by"), pk=object_id)
        if not self.can_view_receipt(request, record):
            raise PermissionDenied
        open_pdf = request.session.get("itam_new_return_pdf") == str(record.pk)
        if open_pdf:
            request.session.pop("itam_new_return_pdf")
        return render(request, "admin/assignments/offboardingrecord/receipt.html", {
            **self.admin_site.each_context(request), "title": "Resumen de devolución",
            "record": record, "items": record.items.select_related("assignment__asset"),
            "open_pdf": open_pdf, "can_manage_record": self.has_view_permission(request, record),
        })

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path("<uuid:object_id>/resumen/", self.admin_site.admin_view(self.receipt_view),
                 name="assignments_offboardingrecord_receipt"),
            path("<uuid:object_id>/activos/<uuid:item_id>/tramitar-baja/",
                 self.admin_site.admin_view(self.link_decommission_view),
                 name="assignments_offboardingrecord_link_decommission"),
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

        if not self.can_view_receipt(request, record):
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
