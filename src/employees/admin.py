from core.admin_audit import StandardHistoryAdmin
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html


from accounts.models import Role

from assignments.forms import OffboardingForm, OffboardingItemFormSet
from assignments.models import (
    Assignment,
    AssignmentStatus,
    OffboardingRecord,
    OffboardingRecordItem,
)
from assignments.services import return_assignment

from .models import Employee, EmployeeStatus, RetiredEmployee


@admin.register(Employee)
class EmployeeAdmin(StandardHistoryAdmin):

    search_fields = ("full_name", "document_number")

    list_display = (
        "full_name",
        "document_type",
        "company",
        "site",
        "area",
        "created_at",
        "view_assigned_assets",
        "process_offboarding",
    )

    def can_process_offboarding(self, request, obj=None):
        user = request.user
        if not (user.is_authenticated and user.is_active and user.is_staff):
            return False
        if user.is_superuser:
            return True
        return (
            user.role in (Role.ADMINISTRATOR, Role.TECHNOLOGY)
            and self.has_change_permission(request, obj)
        )

    def get_list_display(self, request):
        columns = super().get_list_display(request)
        if not self.can_process_offboarding(request):
            return tuple(column for column in columns if column != "process_offboarding")
        return columns

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.resolver_match.url_name in (
            "employees_employee_history",
            "employees_employee_simple_history",
        ):
            return qs

        return qs.filter(
            ~Q(status=EmployeeStatus.RETIRO)
            | Q(assignments__status=AssignmentStatus.ACTIVE)
        ).distinct()

    def view_assigned_assets(self, obj):
        url = (
            f"/admin/assignments/assignment/"
            f"?employee__id__exact={obj.id}"
        )

        return format_html(
            '<a class="button" href="{}">Ver Activos</a>',
            url,
        )

    view_assigned_assets.short_description = "Activos Asignados"

    @admin.display(description="Devolución de activos")
    def process_offboarding(self, obj):
        if obj.status != EmployeeStatus.RETIRO:
            return "—"

        has_pending_assets = obj.assignments.filter(
            status=AssignmentStatus.ACTIVE
        ).exists()

        if not has_pending_assets:
            return format_html(
                '<span style="color:green;font-weight:bold;">Completada</span>'
            )

        url = reverse(
            "admin:employees_employee_process_offboarding",
            args=[obj.pk],
        )

        return format_html(
            '<a class="button" href="{}">Procesar devolución</a>',
            url,
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<uuid:object_id>/process-offboarding/",
                self.admin_site.admin_view(
                    self.process_offboarding_view
                ),
                name="employees_employee_process_offboarding",
            ),
        ]

        return custom_urls + urls

    def process_offboarding_view(self, request, object_id):
        if not self.can_process_offboarding(request):
            raise PermissionDenied
        employee = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.can_process_offboarding(request, employee):
            raise PermissionDenied

        assignments = list(
            Assignment.objects.filter(
                employee=employee,
                status=AssignmentStatus.ACTIVE,
            ).select_related(
                "asset",
                "asset__category",
                "asset__model",
                "asset__model__brand",
            )
        )

        if request.method == "POST":
            form = OffboardingForm(request.POST)

            formset = OffboardingItemFormSet(
                request.POST,
                prefix="items",
            )

            if form.is_valid() and formset.is_valid():

                selected_forms = [
                    item_form
                    for item_form in formset
                    if item_form.cleaned_data.get("selected")
                ]

                if not selected_forms:
                    messages.error(
                        request,
                        "Debes seleccionar al menos un activo para recibir.",
                    )

                else:
                    selected_ids = [
                        item_form.cleaned_data["assignment_id"]
                        for item_form in selected_forms
                    ]

                    try:
                        with transaction.atomic():

                            locked_assignments = list(
                                Assignment.objects.select_for_update(of=("asset",))
                                .filter(
                                    pk__in=selected_ids,
                                    employee=employee,
                                    status=AssignmentStatus.ACTIVE,
                                )
                                .select_related("asset")
                                .order_by("asset_id")
                            )

                            if len(locked_assignments) != len(selected_ids):
                                raise ValidationError(
                                    "Una o más asignaciones ya no están "
                                    "vigentes. Actualiza la página."
                                )

                            forms_by_id = {
                                item_form.cleaned_data["assignment_id"]: item_form
                                for item_form in selected_forms
                            }

                            record = OffboardingRecord.objects.create(
                                employee=employee,
                                received_by=request.user,
                                observations=form.cleaned_data["observations"],
                            )

                            for assignment in locked_assignments:
                                item_form = forms_by_id[assignment.pk]

                                condition = item_form.cleaned_data["condition"]
                                observations = item_form.cleaned_data[
                                    "observations"
                                ]

                                OffboardingRecordItem.objects.create(
                                    offboarding_record=record,
                                    assignment=assignment,
                                    condition=condition,
                                    observations=observations,
                                )

                                return_assignment(
                                    assignment_id=assignment.pk,
                                    condition=condition,
                                    returned_by=request.user,
                                )

                            from inventory.offboarding_pdf import (
                                generate_and_save_offboarding_pdf,
                            )

                            try:
                                return generate_and_save_offboarding_pdf(
                                    record
                                )

                            except Exception as error:
                                messages.error(
                                    request,
                                    "La devolución se registró, "
                                    f"pero ocurrió un error al generar "
                                    f"el PDF: {error}",
                                )

                                return redirect(
                                    reverse(
                                        "admin:employees_employee_change",
                                        args=[employee.pk],
                                    )
                                )

                    except ValidationError as error:
                        messages.error(request, str(error))

        else:
            form = OffboardingForm()

            formset = OffboardingItemFormSet(
                initial=[
                    {"assignment_id": assignment.pk}
                    for assignment in assignments
                ],
                prefix="items",
            )

        rows = [
            {
                "assignment": assignment,
                "form": item_form,
            }
            for assignment, item_form in zip(
                assignments,
                formset.forms,
            )
        ]

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "employee": employee,
            "form": form,
            "formset": formset,
            "rows": rows,
            "title": (
                f"Devolución de activos: "
                f"{employee.full_name}"
            ),
        }

        return render(
            request,
            "admin/employees/employee/process_offboarding.html",
            context,
        )


@admin.register(RetiredEmployee)
class RetiredEmployeeAdmin(admin.ModelAdmin):

    list_display = (
        "full_name",
        "document_number",
        "company",
        "site",
        "area",
        "view_offboarding_records",
    )

    search_fields = (
        "full_name",
        "document_number",
    )

    list_filter = (
        "company",
        "site",
        "area",
    )

    readonly_fields = tuple(
        field.name for field in Employee._meta.fields
    )

    def history_view(self, request, object_id, extra_context=None):
        url = reverse(
            "admin:employees_employee_history",
            args=[object_id],
        )
        return redirect(url)

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        return (
            qs.filter(status=EmployeeStatus.RETIRO)
            .exclude(
                assignments__status=AssignmentStatus.ACTIVE
            )
            .distinct()
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Historial de devoluciones")
    def view_offboarding_records(self, obj):
        url = (
            reverse(
                "admin:assignments_offboardingrecord_changelist"
            )
            + f"?employee__id__exact={obj.pk}"
        )

        return format_html(
            '<a class="button" href="{}">Ver actas</a>',
            url,
        )
