from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, QueryDict
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from assignments.models import Assignment
from core.admin_audit import StandardHistoryAdmin
from employees.models import Employee
from inventory.models import Asset

from .forms import ImportDate, WorkbookUpload
from .models import ImportStatus, StagingAsset
from .services import publish_rows, save_review_edit, set_import_status, stage_workbook
from .workbook import MAX_FILE_BYTES, MAX_ROWS, ROW_FORMS, build_workbook

@admin.register(StagingAsset)
class StagingAssetAdmin(StandardHistoryAdmin):
    change_list_template = "admin/data_imports/import_list.html"
    list_display = ("sheet_name", "row_number", "record_label", "company", "status", "review_state", "created_at")
    list_display_links = ("sheet_name", "record_label")
    list_filter = ("status", "sheet_name", "company", "created_at")
    search_fields = ("legacy_asset_tag", "serial_number", "employee_name", "employee_document", "import_reference")
    ordering = ("-created_at", "sheet_name", "row_number")
    actions = ("approve_selected", "reject_selected", "publish_selected")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def can_upload(self, request):
        return self.has_change_permission(request) and request.user.has_perm("data_imports.add_stagingasset")

    def has_publish_permission(self, request):
        return self.has_change_permission(request) and all(
            self.admin_site.get_model_admin(model).has_add_permission(request) for model in (Employee, Asset, Assignment)
        )

    def get_actions(self, request):
        actions = admin.ModelAdmin.get_actions(self, request)
        return {name: actions[name] for name in self.actions if name in actions}

    @admin.display(description="Registro")
    def record_label(self, obj):
        return obj.employee_name or obj.legacy_asset_tag or obj.serial_number or obj.import_reference or obj.element

    @admin.display(description="Validación")
    def review_state(self, obj):
        if obj.validation_notes:
            return "Requiere revisión"
        return "Sin observaciones" if obj.batch_id else "Carga anterior"

    def get_urls(self):
        custom = [
            path("plantilla/", self.admin_site.admin_view(self.download_workbook), name="data_imports_workbook"),
            path("cargar/", self.admin_site.admin_view(self.upload_workbook), name="data_imports_upload"),
            path("<uuid:object_id>/editar/", self.admin_site.admin_view(self.edit_row), name="data_imports_edit_row"),
            path("<uuid:object_id>/decision/", self.admin_site.admin_view(self.row_decision),
                 name="data_imports_row_decision"),
        ]
        return custom + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, {
            **(extra_context or {}), "title": "Importaciones", "can_upload_workbook": self.can_upload(request),
        })
        if "p" in request.GET and response.status_code == 302 and response.url == f"{request.path}?e=1":
            params = request.GET.copy()
            params.pop("p")
            return redirect(f"{request.path}?{params.urlencode()}" if params else request.path)
        return response

    def download_workbook(self, request):
        if not self.can_upload(request):
            raise PermissionDenied
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotAllowed(["GET", "HEAD"])
        return HttpResponse(
            build_workbook().getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="Plantilla-importacion-ITAM.xlsx"'},
        )

    def upload_workbook(self, request):
        if not self.can_upload(request):
            raise PermissionDenied
        if request.method not in ("GET", "HEAD", "POST"):
            return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
        form = WorkbookUpload(request.POST, request.FILES) if request.method == "POST" else WorkbookUpload()
        form.fields["workbook"].help_text = f"Formato .xlsx. Hasta {MAX_ROWS} filas y {MAX_FILE_BYTES // (1024 * 1024)} MiB."
        if form.is_valid():
            try:
                batch, total, invalid = stage_workbook(form.cleaned_data["workbook"], request.user)
            except ValidationError as error:
                form.add_error("workbook", error)
            else:
                level = messages.WARNING if invalid else messages.SUCCESS
                self.message_user(request, f"{total} filas en revisión. {invalid} requieren corrección.", level)
                return redirect(f"{reverse('admin:data_imports_stagingasset_changelist')}?batch_id__exact={batch}")
        return TemplateResponse(request, "admin/data_imports/upload.html", {
            **self.admin_site.each_context(request), "opts": self.opts, "title": "Cargar Excel para revisión", "form": form,
        })

    def row_navigation(self, request, row):
        filters = QueryDict(request.GET.get("_changelist_filters", "")).urlencode()
        preserved = self.get_preserved_filters(request)
        suffix = f"?{preserved}" if preserved else ""
        listing = reverse("admin:data_imports_stagingasset_changelist")
        return {
            "return_url": f"{listing}?{filters}" if filters else listing,
            "detail_url": reverse("admin:data_imports_stagingasset_change", args=[row.pk]) + suffix,
            "edit_url": reverse("admin:data_imports_edit_row", args=[row.pk]) + suffix,
            "decision_url": reverse("admin:data_imports_row_decision", args=[row.pk]) + suffix,
        }

    def change_view(self, request, object_id, form_url="", extra_context=None):
        row = self.get_object(request, object_id)
        if row is None:
            raise Http404
        if not self.has_view_or_change_permission(request, row):
            raise PermissionDenied
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotAllowed(["GET", "HEAD"])
        form = ROW_FORMS.get(row.sheet_name) if row.batch_id else None
        if form:
            values = [(field.label, row.workbook_data.get(key)) for key, field in form.base_fields.items()]
        else:
            fields = ("employee_name", "employee_document", "element", "legacy_asset_tag", "serial_number",
                      "brand", "model", "company", "site", "area", "ram", "storage", "processor",
                      "operating_system", "hostname", "mac_address", "observations")
            values = [(self.model._meta.get_field(key).verbose_name, getattr(row, key)) for key in fields]
        return TemplateResponse(request, "admin/data_imports/review.html", {
            **self.admin_site.each_context(request), **(extra_context or {}),
            **self.row_navigation(request, row),
            "opts": self.opts, "title": f"{row.sheet_name} · fila {row.row_number}", "row": row, "values": values,
            "can_decide": self.has_change_permission(request, row) and row.status != ImportStatus.IMPORTED,
            "can_edit": form and self.has_change_permission(request, row) and row.status != ImportStatus.IMPORTED,
            "can_publish": row.batch_id and row.status == ImportStatus.APPROVED and self.has_publish_permission(request),
            "can_view_history": self.has_view_history_or_change_history_permission(request, row),
        })

    def edit_row(self, request, object_id):
        row = get_object_or_404(self.get_queryset(request), pk=object_id)
        form_class = ROW_FORMS.get(row.sheet_name) if row.batch_id else None
        if not form_class or row.status == ImportStatus.IMPORTED or not self.has_change_permission(request, row):
            raise PermissionDenied
        if request.method not in ("GET", "HEAD", "POST"):
            return HttpResponseNotAllowed(["GET", "HEAD", "POST"])

        is_post = request.method == "POST"
        version = request.POST.get("version", "") if is_post else row.updated_at.isoformat()
        form = form_class(request.POST if is_post else None, initial=row.workbook_data)
        for field in form.fields.values():
            if isinstance(field, forms.ChoiceField) and not field.required:
                field.choices = [("", "Sin indicar"), *field.choices]
            if isinstance(field, ImportDate):
                field.help_text = "Formato AAAA-MM-DD."
        for name in ("observations", "warranty_observations", "initial_condition", "assignment_observations"):
            if name in form.fields:
                form.fields[name].widget = forms.Textarea(attrs={"rows": 3})

        navigation = self.row_navigation(request, row)
        if form.is_valid():
            try:
                changed = save_review_edit(
                    self.get_queryset(request).filter(pk=row.pk), data=form.cleaned_data,
                    version=version, actor=request.user,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if changed:
                    self.message_user(request, "Cambios guardados. Revisa y aprueba la fila para publicarla.", messages.SUCCESS)
                else:
                    self.message_user(request, "La fila ya tenía esos datos.", messages.INFO)
                return redirect(navigation["detail_url"])

        return TemplateResponse(request, "admin/data_imports/edit_row.html", {
            **self.admin_site.each_context(request), **navigation, "opts": self.opts,
            "title": f"Editar fila {row.row_number} · {row.sheet_name}",
            "row": row, "edit_form": form, "version": version,
        })

    @transaction.atomic
    def row_decision(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        queryset = self.get_queryset(request).filter(pk=object_id)
        row = get_object_or_404(queryset.select_for_update())
        if not self.has_change_permission(request, row):
            raise PermissionDenied
        detail_url = self.row_navigation(request, row)["detail_url"]
        version = request.POST.get("version")
        if version is not None and version != row.updated_at.isoformat():
            self.message_user(request, "La fila cambió. Revisa sus datos antes de tomar una decisión.", messages.WARNING)
            return redirect(detail_url)
        decision = request.POST.get("decision")
        if decision == "publish":
            if not self.has_publish_permission(request):
                raise PermissionDenied
            self.publish_selected(request, queryset)
        elif decision == "approve":
            self.approve_selected(request, queryset)
        elif decision == "reject":
            self.reject_selected(request, queryset)
        else:
            raise PermissionDenied
        return redirect(detail_url)

    @admin.action(description="Aprobar filas para publicar", permissions=["change"])
    def approve_selected(self, request, queryset):
        changed, invalid = set_import_status(queryset, ImportStatus.APPROVED, request.user)
        self.message_user(request, f"{changed} filas aprobadas. {invalid} requieren corrección.",
                          messages.WARNING if invalid else messages.SUCCESS)

    @admin.action(description="Descartar filas seleccionadas", permissions=["change"])
    def reject_selected(self, request, queryset):
        changed, _ = set_import_status(queryset, ImportStatus.REJECTED, request.user)
        self.message_user(request, f"{changed} filas descartadas.", messages.SUCCESS)

    @admin.action(description="Pasar a producción las filas aprobadas", permissions=["publish"])
    def publish_selected(self, request, queryset):
        published, failed = publish_rows(queryset, request.user)
        if not published and not failed:
            self.message_user(request, "La selección no tiene filas aprobadas de la plantilla vigente.", messages.WARNING)
            return
        self.message_user(request, f"{published} filas publicadas. {failed} requieren revisión.",
                          messages.SUCCESS if published and not failed else messages.WARNING)
