import os
from uuid import uuid4
from django.conf import settings
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from django.db import transaction
from weasyprint import HTML
from django.utils import timezone
from inventory.models import AssetStatus
from .models import Assignment, AssignmentStatus

def generate_act_pdf(assignment, *, include_active_custody=False):
    assignments = assignment.delivery_assignments()
    if include_active_custody:
        assignments = Assignment.objects.filter(
            employee_id=assignment.employee_id, status=AssignmentStatus.ACTIVE, returned_at__isnull=True,
        ).exclude(asset__status=AssetStatus.DECOMMISSIONED)
    assignments = list(assignments.select_related('asset__category', 'asset__model', 'asset__brand'))
    if not assignments:
        raise AssignmentActError("El empleado no tiene activos vigentes para consolidar.")

    delivery = assignments[0] if not include_active_custody else assignment
    delivery_date = timezone.now() if include_active_custody else delivery.assigned_at
    grouped_delivery = bool(assignment.delivery_id and not include_active_custody)
    context = {
        'company': assignment.employee.company if grouped_delivery else assignment.asset.company,
        'site': assignment.employee.site if grouped_delivery else assignment.asset.site,
        'area': assignment.employee.area,
        'employee': assignment.employee,
        'assignments': assignments,
        'consolidated': include_active_custody,
        'show_conditions': grouped_delivery,
        'initial_condition': assignment.initial_condition if not (include_active_custody or grouped_delivery) else '',
        'assigned_by': assignment.assigned_by,
        'date': timezone.localtime(delivery_date).strftime('%d de %B de %Y'),
        'observations': 'Inventario bajo custodia vigente' if include_active_custody else assignment.observations,
        'logo_acepalma': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_acepalma.png')}",
        'logo_solutrans': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_solutrans.png')}",
    }
    
    html_string = render_to_string('assignments/pdf_template.html', context)
    pdf_bytes = HTML(string=html_string).write_pdf()
    
    filename = f"acta-{uuid4()}.pdf"
    assignment.signed_act_pdf.save(filename, ContentFile(pdf_bytes), save=False)
    return assignment.signed_act_pdf


class AssignmentActError(Exception):
    """El acta no se pudo generar o almacenar."""


def issue_assignment_act(assignment_id, *, actor, include_active_custody=False):
    assignment = None
    previous_file = None
    try:
        with transaction.atomic():
            target = Assignment.objects.get(pk=assignment_id)
            scope = (Assignment.objects.filter(pk=assignment_id) if include_active_custody
                     else target.delivery_assignments())
            recipients = list(scope.select_for_update().order_by("pk"))
            assignment = next(item for item in recipients if item.pk == assignment_id)
            previous_file = assignment.signed_act_pdf.name
            if assignment.status != AssignmentStatus.ACTIVE or assignment.returned_at is not None:
                raise AssignmentActError("La asignación ya no está vigente.")
            generate_act_pdf(assignment, include_active_custody=include_active_custody)
            save_assignment_act(assignment, recipients, actor=actor, custody=include_active_custody)
    except Exception as error:
        discard_new_act(assignment, previous_file)
        if isinstance(error, AssignmentActError):
            raise
        raise AssignmentActError from error


def save_assignment_act(assignment, recipients, *, actor, custody=False):
    for item in recipients:
        item.signed_act_pdf = assignment.signed_act_pdf.name
        item._history_user = actor
        item._change_reason = (
            "Generación de acta de custodia vigente" if custody
            else "Generación de acta de entrega"
        )
        item.save(update_fields=["signed_act_pdf"])


def discard_new_act(assignment, previous_file=None):
    if assignment and assignment.signed_act_pdf and assignment.signed_act_pdf.name != previous_file:
        try:
            assignment.signed_act_pdf.delete(save=False)
        except OSError:
            pass
