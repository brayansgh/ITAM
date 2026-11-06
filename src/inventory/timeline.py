"""Cronología paginada basada en fechas operativas explícitas, sin reconstrucciones."""
from django.core.paginator import Paginator
from django.db.models import F, Value, CharField
from django.urls import reverse


def asset_timeline(request, asset, admin_site):
    from assignments.models import Assignment
    from maintenance.models import MaintenanceRecord
    assignment_admin = admin_site._registry[Assignment]
    maintenance_admin = admin_site._registry[MaintenanceRecord]
    can_assignments = assignment_admin.has_view_permission(request)
    can_maintenance = maintenance_admin.has_view_permission(request)
    assignments = assignment_admin.get_queryset(request).filter(asset_id=asset.pk)
    tickets = maintenance_admin.get_queryset(request).filter(asset_id=asset.pk)
    if not can_assignments:
        assignments = assignments.none()
    if not can_maintenance:
        tickets = tickets.none()

    def stream(qs, date_field, kind):
        return qs.order_by().annotate(
            event_date=F(date_field), event_id=F("pk"),
            event_kind=Value(kind, output_field=CharField()),
        ).values("event_date", "event_id", "event_kind")

    events = stream(assignments, "assigned_at", "assignment").union(
        stream(assignments.filter(returned_at__isnull=False), "returned_at", "return"),
        stream(tickets, "created_at", "maintenance"), all=True,
    ).order_by("-event_date", "-event_kind", "-event_id")
    page = Paginator(events, 25).get_page(request.GET.get("timeline_page"))
    raw = list(page.object_list)
    assignment_ids = [row["event_id"] for row in raw if row["event_kind"] != "maintenance"]
    ticket_ids = [row["event_id"] for row in raw if row["event_kind"] == "maintenance"]
    assignment_map = {obj.pk: obj for obj in assignments.filter(pk__in=assignment_ids).select_related(
        "employee", "assigned_by", "offboarding_item__offboarding_record__received_by",
    )}
    ticket_map = {obj.pk: obj for obj in tickets.filter(pk__in=ticket_ids).select_related("reported_by")}
    rows = []
    for row in raw:
        if row["event_kind"] == "maintenance":
            obj = ticket_map.get(row["event_id"])
            if obj is None or not maintenance_admin.has_view_permission(request, obj):
                continue
            row.update(action="Mantenimiento registrado", person=str(obj.reported_by),
                       detail=f"{obj.get_type_display()} · Estado actual: {obj.get_status_display()} · {obj.description}",
                       url=reverse("admin:maintenance_maintenancerecord_change", args=[obj.pk]))
        else:
            obj = assignment_map.get(row["event_id"])
            if obj is None or not assignment_admin.has_view_permission(request, obj):
                continue
            if row["event_kind"] == "assignment":
                row.update(action="Asignación registrada", person=str(obj.assigned_by),
                           detail=f"{obj.employee.full_name} · {obj.initial_condition} · Estado actual: {obj.get_status_display()}")
            else:
                item = getattr(obj, "offboarding_item", None)
                row.update(action="Devolución registrada", person=(str(item.offboarding_record.received_by) if item else "Sin responsable registrado"),
                           detail=f"{obj.employee.full_name} · {obj.return_condition or 'Sin condición registrada'}")
            row["url"] = reverse("admin:assignments_assignment_change", args=[obj.pk])
        rows.append(row)
    current = assignments.filter(status="ACTIVE").select_related("employee").first()
    return {"rows": rows, "page": page, "can_assignments": can_assignments,
            "can_maintenance": can_maintenance, "custodian": current.employee.full_name if current else None,
            "missing_return_dates": assignments.filter(status="RETURNED", returned_at__isnull=True).count()}
