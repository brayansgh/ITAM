from core.admin_audit import StandardHistoryAdmin
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import urlencode


from accounts.models import Role

from assignments.forms import ActiveReturnForm, OffboardingForm, OffboardingItemFormSet
from assignments.models import (
    Assignment,
    AssignmentStatus,
    OffboardingRecord,
    OffboardingRecordItem,
)
from assignments.services import ReturnPdfError, discard_return_pdf, register_active_returns, return_assignment
from inventory.models import Asset

from .models import Employee, EmployeeStatus, RetiredEmployee


@admin.register(Employee)
class EmployeeAdmin(StandardHistoryAdmin):
    list_per_page = 25
    change_form_template = 'admin/employees/employee/profile.html'
    list_filter = ('company', 'site', 'area', 'status')
    fieldsets = (
        ('Identificación', {'fields': ('full_name', 'document_type', 'document_number')}),
        ('Organización', {'fields': ('company', 'site', 'area', 'status')}),
        ('Contacto', {'fields': ('email', 'phone')}),
    )

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj:
            context['employee_detail'] = request.method == 'GET' and request.GET.get('editar') != '1'
            context['employee_edit_url'] = request.path + '?editar=1'
            aa = self.admin_site._registry[Assignment]
            assignments = aa.get_queryset(request).filter(employee=obj).select_related('asset') if aa.has_view_permission(request) else Assignment.objects.none()
            context['employee_custody'] = assignments.filter(status=AssignmentStatus.ACTIVE)[:100]
            context['employee_assignments'] = assignments[:100]
            context['can_employee_custody'] = aa.has_view_permission(request)
            if context['employee_detail']:
                context["employee_documents"] = self.employee_documents(request, obj, assignments, aa)
                if self.can_process_offboarding(request, obj):
                    route = ("employees_employee_process_offboarding" if obj.status == EmployeeStatus.RETIRO
                             else "employees_employee_start_offboarding")
                    context["employee_offboarding_url"] = reverse(f"admin:{route}", args=[obj.pk])
                if self.has_view_history_or_change_history_permission(request, obj):
                    context['employee_history_url'] = reverse('admin:employees_employee_history', args=[obj.pk])
                if (obj.status != EmployeeStatus.RETIRO
                        and aa.has_add_permission(request)
                        and self.admin_site.get_model_admin(Asset).has_view_permission(request)):
                    employee_query = '?' + urlencode({'employee': obj.pk})
                    context['employee_assignment_url'] = reverse('admin:assignments_assignment_add') + employee_query
                    context['employee_loan_url'] = reverse('admin:assignments_assignment_loan') + employee_query

            if (context['employee_detail'] and obj.status == EmployeeStatus.ACTIVE
                    and self.can_process_offboarding(request, obj)
                    and context['can_employee_custody'] and context['employee_custody'].exists()):
                context['active_return_url'] = reverse('admin:employees_employee_return_assets', args=[obj.pk])
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change and obj.status == EmployeeStatus.RETIRO:
            previous_status = (
                Employee.objects.select_for_update().filter(pk=obj.pk)
                .values_list("status", flat=True).first()
            )
        super().save_model(request, obj, form, change)
        request.itam_new_retirement = (
            obj.status == EmployeeStatus.RETIRO and previous_status != EmployeeStatus.RETIRO
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if getattr(request, "itam_new_retirement", False):
            self.issue_retirement_without_custody(request, form.instance)

    def issue_retirement_without_custody(self, request, employee):
        if employee.assignments.filter(status=AssignmentStatus.ACTIVE).exists():
            return None
        if not self.can_process_offboarding(request, employee):
            raise PermissionDenied

        from inventory.offboarding_pdf import generate_and_save_offboarding_pdf

        record = OffboardingRecord(employee=employee, received_by=request.user)
        record._history_user = request.user
        record.save()
        request.itam_retirement_record = record
        try:
            generate_and_save_offboarding_pdf(record)
        except Exception as error:
            raise ReturnPdfError from error
        return record

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ReturnPdfError:
            discard_return_pdf(request.itam_retirement_record)
            messages.error(request, "No se pudo generar el acta de desvinculación. El retiro no se registró.")
            return redirect(request.get_full_path())
        except Exception:
            discard_return_pdf(getattr(request, "itam_retirement_record", None))
            raise

    def response_add(self, request, obj, post_url_continue=None):
        if hasattr(request, "itam_retirement_record") and "_popup" not in request.POST:
            return self.return_receipt_redirect(request, request.itam_retirement_record)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if hasattr(request, "itam_retirement_record") and "_popup" not in request.POST:
            return self.return_receipt_redirect(request, request.itam_retirement_record)
        return super().response_change(request, obj)

    def employee_documents(self, request, employee, assignments, assignment_admin):
        documents = []
        seen = set()
        for assignment in assignments.exclude(signed_act_pdf="").exclude(signed_act_pdf__isnull=True):
            name = assignment.signed_act_pdf.name
            if name in seen or not assignment_admin.has_view_permission(request, assignment):
                continue
            seen.add(name)
            documents.append({
                "label": ("Acta de préstamo de activos" if assignment.due_on else
                          "Acta de entrega de activos" if assignment.delivery_id else f"Acta de entrega · {assignment.asset}"),
                "date": assignment.assigned_at,
                "url": reverse("download_act_pdf", args=[assignment.pk]),
            })
        returns_admin = self.admin_site._registry[OffboardingRecord]
        for record in returns_admin.get_queryset(request).filter(employee=employee).select_related("employee").exclude(pdf="").exclude(pdf__isnull=True):
            if returns_admin.can_view_receipt(request, record):
                documents.append({"label": record.document_title, "date": record.created_at,
                                  "url": reverse("admin:assignments_offboardingrecord_view_pdf", args=[record.pk]),
                                  "receipt_url": reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk])})
        return sorted(documents, key=lambda document: document["date"], reverse=True)

    search_fields = ("full_name", "document_number")

    def get_search_results(self, request, queryset, search_term):
        if (getattr(getattr(request, 'resolver_match', None), 'url_name', None) == 'autocomplete'
                and request.GET.get('app_label') == 'assignments'
                and request.GET.get('model_name') == 'assignment'
                and request.GET.get('field_name') == 'employee'):
            queryset = queryset.exclude(status=EmployeeStatus.RETIRO).order_by('full_name', 'pk')
        return super().get_search_results(request, queryset, search_term)

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

        if getattr(getattr(request, 'resolver_match', None), 'url_name', '') in (
            "employees_employee_history",
            "employees_employee_simple_history",
        ):
            return qs

        pending = Assignment.objects.filter(employee_id=OuterRef("pk"), status=AssignmentStatus.ACTIVE)
        return qs.annotate(has_pending_assets=Exists(pending)).filter(
            ~Q(status=EmployeeStatus.RETIRO) | Q(has_pending_assets=True)
        )

    def view_assigned_assets(self, obj):
        url = (
            f"/admin/assignments/assignment/"
            f"?employee__id__exact={obj.id}"
        )

        return format_html(
            '<a class="itam-table-action" href="{}">Ver Activos</a>',
            url,
        )

    view_assigned_assets.short_description = "Activos Asignados"

    @admin.display(description="Devolución de activos")
    def process_offboarding(self, obj):
        if obj.status not in (EmployeeStatus.ACTIVE, EmployeeStatus.RETIRO):
            return "—"

        has_pending_assets = obj.has_pending_assets

        if not has_pending_assets and obj.status == EmployeeStatus.ACTIVE:
            return "—"
        if not has_pending_assets:
            return format_html(
                '<span class="itam-label itam-status-success">Completada</span>'
            )

        if obj.status == EmployeeStatus.ACTIVE:
            return format_html('<a class="itam-table-action" href="{}">Devolver activos</a>',
                               reverse("admin:employees_employee_return_assets", args=[obj.pk]))

        url = reverse(
            "admin:employees_employee_process_offboarding",
            args=[obj.pk],
        )

        return format_html(
            '<a class="itam-table-action" href="{}">Procesar desvinculación</a>',
            url,
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path("<uuid:object_id>/desvincular/", self.admin_site.admin_view(self.start_offboarding_view),
                 name="employees_employee_start_offboarding"),
            path("<uuid:object_id>/devolver/", self.admin_site.admin_view(self.return_assets_view),
                 name="employees_employee_return_assets"),
            path(
                "<uuid:object_id>/process-offboarding/",
                self.admin_site.admin_view(
                    self.process_offboarding_view
                ),
                name="employees_employee_process_offboarding",
            ),
        ]

        return custom_urls + urls

    def start_offboarding_view(self, request, object_id):
        from django.http import HttpResponseNotAllowed

        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])
        if not self.can_process_offboarding(request):
            raise PermissionDenied
        employee = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.can_process_offboarding(request, employee):
            raise PermissionDenied
        process_url = reverse("admin:employees_employee_process_offboarding", args=[employee.pk])
        if employee.status == EmployeeStatus.RETIRO:
            return redirect(process_url)

        if request.method == "POST":
            try:
                with transaction.atomic():
                    employee = Employee.objects.select_for_update().get(pk=employee.pk)
                    if not self.can_process_offboarding(request, employee):
                        raise PermissionDenied
                    if employee.status == EmployeeStatus.RETIRO:
                        return redirect(process_url)
                    employee.status = EmployeeStatus.RETIRO
                    employee._history_user = request.user
                    employee.save(update_fields=["status", "updated_at"])
                    record = self.issue_retirement_without_custody(request, employee)
                    self.log_change(request, employee, [{"changed": {"fields": ["Estado"]}}])
            except ReturnPdfError:
                discard_return_pdf(request.itam_retirement_record)
                messages.error(request, "No se pudo generar el acta de desvinculación. El retiro no se registró.")
                return redirect(request.path)
            except Exception:
                discard_return_pdf(getattr(request, "itam_retirement_record", None))
                raise
            if record:
                return self.return_receipt_redirect(request, record)
            messages.success(request, "Retiro registrado. Confirma los activos que recibas físicamente.")
            return redirect(process_url)

        return render(request, "admin/employees/employee/confirm_offboarding.html", {
            **self.admin_site.each_context(request),
            "title": "Desvinculación",
            "opts": self.model._meta,
            "employee": employee,
            "has_pending_assets": employee.has_pending_assets,
        })

    def return_assets_view(self, request, object_id):
        from maintenance.models import MaintenanceRecord

        if not self.can_process_offboarding(request):
            raise PermissionDenied
        employee = get_object_or_404(self.get_queryset(request), pk=object_id, status=EmployeeStatus.ACTIVE)
        if not self.can_process_offboarding(request, employee):
            raise PermissionDenied
        assignment_admin = self.admin_site._registry[Assignment]
        if not assignment_admin.has_view_permission(request):
            raise PermissionDenied
        assignments = assignment_admin.get_queryset(request).filter(
            employee=employee, status=AssignmentStatus.ACTIVE,
        ).select_related("asset__category", "asset__brand", "asset__model", "asset__network").order_by("asset__asset_tag")
        maintenance_admin = self.admin_site._registry[MaintenanceRecord]
        can_decommission = maintenance_admin.can_manage_return_links(request)
        form = ActiveReturnForm(
            request.POST if request.method == "POST" else None,
            assignments=assignments, can_request_decommission=can_decommission,
        )
        if request.method == "POST":
            if request.POST.get("request_decommission") and not can_decommission:
                raise PermissionDenied
            if form.is_valid():
                selected = form.cleaned_data["assignments"]
                if any(not assignment_admin.has_view_permission(request, assignment) for assignment in selected):
                    raise PermissionDenied

                def authorize(ticket):
                    if not maintenance_admin.can_link_return(request, ticket):
                        raise PermissionDenied

                try:
                    record, tickets = register_active_returns(
                        employee=employee, assignments=selected, reason=form.cleaned_data["reason"],
                        condition=form.cleaned_data["condition"], observations=form.cleaned_data["observations"],
                        actor=request.user, authorize_decommission=authorize
                        if form.cleaned_data.get("request_decommission") else None,
                    )
                except ValidationError as error:
                    form.add_error(None, error.messages)
                except ReturnPdfError:
                    form.add_error(None, "No se pudo generar el acta. La devolución no se registró.")
                else:
                    messages.success(request, f"Devolución registrada. El acta incluye {len(selected)} activo(s).")
                    if tickets:
                        messages.success(request, f"Trámites de baja vinculados: {len(tickets)}.")
                    return self.return_receipt_redirect(request, record)
        return render(request, "admin/employees/employee/return_assets.html", {
            **self.admin_site.each_context(request), "title": "Devolver activos",
            "employee": employee, "form": form, "has_assignments": assignments.exists(),
        })

    def return_receipt_redirect(self, request, record):
        request.session["itam_new_return_pdf"] = str(record.pk)
        return redirect(reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk]))

    def process_offboarding_view(self, request, object_id):
        if not self.can_process_offboarding(request):
            raise PermissionDenied
        employee = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.can_process_offboarding(request, employee):
            raise PermissionDenied
        if employee.status == EmployeeStatus.ACTIVE:
            return redirect(reverse("admin:employees_employee_return_assets", args=[employee.pk]))

        assignments = list(
            Assignment.objects.filter(
                employee=employee,
                status=AssignmentStatus.ACTIVE,
            ).select_related(
                "asset",
                "asset__category",
                "asset__model",
                "asset__brand",
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

                    record = None
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

                            locked_employee = Employee.objects.select_for_update().get(pk=employee.pk)
                            if locked_employee.status != EmployeeStatus.RETIRO:
                                raise ValidationError("El empleado ya no figura como retirado. Actualiza la página.")

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
                                generate_and_save_offboarding_pdf(record)
                            except Exception as error:
                                raise ReturnPdfError from error

                    except ReturnPdfError:
                        discard_return_pdf(record)
                        messages.error(request, "No se pudo generar el acta. La devolución no se registró.")
                    except ValidationError as error:
                        discard_return_pdf(record)
                        messages.error(request, str(error))
                    except Exception:
                        discard_return_pdf(record)
                        raise
                    else:
                        return self.return_receipt_redirect(request, record)

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
                f"Desvinculación: "
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

    actions = None

    list_display = (
        "full_name",
        "document_number",
        "company",
        "site",
        "area",
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
            .prefetch_related(Prefetch(
                "offboarding_records",
                queryset=OffboardingRecord.objects.filter(return_reason="").exclude(pdf="").exclude(pdf__isnull=True),
                to_attr="retirement_documents",
            ))
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {**(extra_context or {}), "title": "Empleados retirados"})

    def has_change_permission(self, request, obj=None):
        return False

    def get_list_display(self, request):
        record_admin = self.admin_site.get_model_admin(OffboardingRecord)

        @admin.display(description="Actas de desvinculación")
        def documents(employee):
            links = [
                (reverse("admin:assignments_offboardingrecord_receipt", args=[record.pk]), record.created_at)
                for record in employee.retirement_documents
                if record_admin.can_view_receipt(request, record)
            ]
            if not links:
                return "Sin actas disponibles"
            from django.utils import timezone
            from django.utils.html import format_html_join

            actions = format_html_join(
                "", '<a class="itam-table-action" href="{}">Acta de desvinculación · {}</a>',
                ((url, timezone.localtime(date).strftime("%d/%m/%Y")) for url, date in links),
            )
            return format_html('<div class="itam-table-actions">{}</div>', actions)

        return (*super().get_list_display(request), documents)
