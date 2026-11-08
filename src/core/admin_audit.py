from django.contrib.admin.models import LogEntry
from django.contrib.admin.utils import unquote
from django.contrib.auth import get_permission_codename, get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.migrations.recorder import MigrationRecorder
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from .audit import version_row


class StandardHistoryAdmin(SimpleHistoryAdmin):
    """Historial de datos y eventos de Admin separados, sin sumar duplicados."""

    object_history_template = "admin/core/audit_history.html"
    audit_related_models = ()
    audit_page_size = 50

    def get_actions(self, request):
        """La gestión se realiza por registro, sin acciones masivas en listados."""
        return {}

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {'title': str(self.opts.verbose_name_plural).capitalize(), **(extra_context or {})})

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            # ModelAdmin termina su transacción antes de devolver esta excepción.
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            if request.method != "POST":
                raise
            from django.contrib import messages
            self.message_user(request, "No se guardaron los cambios: " + "; ".join(error.messages), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        # Restaurar una versión saltaría los servicios de asignación/devolución.
        raise PermissionDenied("La auditoría es de solo lectura.")

    def history_view(self, request, object_id, extra_context=None):
        object_id = unquote(object_id)
        # Los proxies heredan el gestor, pero no el metadato de Options.
        metadata = self.model._meta.concrete_model._meta
        history = getattr(self.model, metadata.simple_history_manager_attribute)
        records = history.filter(**{self.model._meta.pk.attname: object_id}).order_by("-history_date", "-history_id")
        try:
            obj = self.get_queryset(request).get(pk=object_id)
        except self.model.DoesNotExist:
            latest = records.first()
            if latest is None:
                raise Http404
            obj = latest.instance
        if not self.has_view_history_or_change_history_permission(request, obj):
            raise PermissionDenied

        counts = records.aggregate(
            total=Count("history_id"), created=Count("history_id", filter=Q(history_type="+")),
            modified=Count("history_id", filter=Q(history_type="~")),
            deleted=Count("history_id", filter=Q(history_type="-")),
        )
        page = Paginator(records.select_related("history_user"), self.audit_page_size).get_page(request.GET.get("page"))
        # Una fila adicional permite comparar el final de la página sin consultar
        # una versión anterior por cada fila (ni usar datos de otra entidad).
        start = page.start_index() - 1 if counts["total"] else 0
        batch = list(records.select_related("history_user")[start:start + self.audit_page_size + 1])
        relations_since = None
        if records.model is get_user_model().history.model:
            relations_since = MigrationRecorder.Migration.objects.using(records.db).filter(
                app="inventory", name="0007_estandarizar_auditoria",
            ).values_list("applied", flat=True).first()
        rows = [version_row(record, batch[index + 1] if index + 1 < len(batch) else None, relations_since)
                for index, record in enumerate(batch[:self.audit_page_size])]
        content_type = ContentType.objects.get_for_model(self.model)
        events = LogEntry.objects.filter(content_type=content_type, object_id=str(object_id)).select_related("user").order_by("-action_time", "-pk")
        event_page = Paginator(events, self.audit_page_size).get_page(request.GET.get("events_page"))

        related = []
        related_count = 0
        for model, field_name in self.audit_related_models:
            opts = model._meta
            if not any(request.user.has_perm(f"{opts.app_label}.{get_permission_codename(action, opts)}")
                       for action in ("view", "change")):
                continue
            stream = model.history.filter(**{field_name + "_id": object_id}).select_related("history_user").order_by("-history_date", "-history_id")
            related_count += stream.count()
            for record in stream[:self.audit_page_size]:
                row = version_row(record, record.prev_record)
                row["entity"] = f"{model._meta.verbose_name}: {record.instance.pk}"
                related.append(row)
        related.sort(key=lambda row: row["date"], reverse=True)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta, "app_label": self.model._meta.app_label,
            "object": obj, "title": f"Historial: {obj}",
            "module_name": str(self.model._meta.verbose_name_plural),
            "audit_rows": rows, "audit_counts": counts, "audit_page": page,
            "admin_events": event_page, "related_rows": related[:self.audit_page_size],
            "related_count": related_count, "audit_timezone": timezone.get_current_timezone_name(),
        }
        context.update(extra_context or {})
        request.current_app = self.admin_site.name
        return TemplateResponse(request, self.object_history_template, context)
