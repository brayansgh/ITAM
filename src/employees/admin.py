from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.db.models import Q
from simple_history.admin import SimpleHistoryAdmin

from .models import Employee, EmployeeStatus, RetiredEmployee
from assignments.models import (
    Assignment,
    AssignmentStatus,
    OffboardingRecord,
    OffboardingRecordItem,
)
from assignments.forms import OffboardingForm, OffboardingItemFormSet
from inventory.models import AssetStatus


@admin.register(Employee)
class EmployeeAdmin(SimpleHistoryAdmin):

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Permitir consultar el historial de cualquier empleado,
        # incluso si está retirado y no tiene activos pendientes.
        if request.resolver_match.url_name in (
            "employees_employee_history",
            "employees_employee_simple_history",
        ):
            return qs
        # Filtro normal de la lista de empleados.
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
        employee = get_object_or_404(Employee, pk=object_id)

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
                            # Bloqueamos las asignaciones para evitar
                            # procesar una devolución simultánea.
                            locked_assignments = list(
                                Assignment.objects.select_for_update().filter(
                                    pk__in=selected_ids,
                                    employee=employee,
                                    status=AssignmentStatus.ACTIVE,
                                ).select_related("asset")
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
                                observations = item_form.cleaned_data["observations"]

                                OffboardingRecordItem.objects.create(
                                    offboarding_record=record,
                                    assignment=assignment,
                                    condition=condition,
                                    observations=observations,
                                )

                                assignment.status = AssignmentStatus.RETURNED
                                assignment.returned_at = timezone.now()
                                assignment.return_condition = condition
                                assignment.save(
                                    update_fields=[
                                        "status",
                                        "returned_at",
                                        "return_condition",
                                        "updated_at",
                                    ]
                                )

                                asset = assignment.asset
                                asset.status = AssetStatus.AVAILABLE
                                asset.save(
                                    update_fields=["status", "updated_at"]
                                )

                            from inventory.offboarding_pdf import generate_and_save_offboarding_pdf

                            try:
                                return generate_and_save_offboarding_pdf(record)

                            except Exception as error:
                                messages.error(
                                    request,
                                    f"La devolución se registró, pero ocurrió un error "
                                    f"al generar el PDF: {error}",
                                )

                                return redirect(
                                    reverse(
                                        "admin:employees_employee_change",
                                        args=[employee.pk],
                                    )
                                )

                    except ValidationError as error:
                        messages.error(request, error.message)

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
            {"assignment": assignment, "form": item_form}
            for assignment, item_form in zip(assignments, formset.forms)
        ]

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "employee": employee,
            "form": form,
            "formset": formset,
            "rows": rows,
            "title": f"Devolución de activos: {employee.full_name}",
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
