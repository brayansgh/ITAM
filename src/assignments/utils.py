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
    assignments = Assignment.objects.filter(pk=assignment.pk)
    if include_active_custody:
        assignments = Assignment.objects.filter(
            employee_id=assignment.employee_id, status=AssignmentStatus.ACTIVE, returned_at__isnull=True,
        ).exclude(asset__status=AssetStatus.DECOMMISSIONED)
    assignments = list(assignments.select_related('asset__category', 'asset__model', 'asset__brand'))
    if not assignments:
        raise AssignmentActError("El empleado no tiene activos vigentes para consolidar.")

    delivery_date = timezone.now() if include_active_custody else assignment.assigned_at
    context = {
        'company': assignment.asset.company,
        'site': assignment.asset.site,
        'area': assignment.employee.area,
        'employee': assignment.employee,
        'assignments': assignments,
        'consolidated': include_active_custody,
        'initial_condition': assignment.initial_condition if not include_active_custody else '',
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
            assignment = Assignment.objects.select_for_update().get(pk=assignment_id)
            previous_file = assignment.signed_act_pdf.name
            if assignment.status != AssignmentStatus.ACTIVE or assignment.returned_at is not None:
                raise AssignmentActError("La asignación ya no está vigente.")
            generate_act_pdf(assignment, include_active_custody=include_active_custody)
            assignment._history_user = actor
            assignment._change_reason = (
                "Generación de acta de custodia vigente" if include_active_custody
                else "Generación de acta de entrega"
            )
            assignment.save(update_fields=["signed_act_pdf"])
    except Exception as error:
        if assignment and assignment.signed_act_pdf and assignment.signed_act_pdf.name != previous_file:
            try:
                assignment.signed_act_pdf.delete(save=False)
            except OSError:
                pass
        if isinstance(error, AssignmentActError):
            raise
        raise AssignmentActError from error
