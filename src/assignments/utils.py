import os
from django.conf import settings
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from weasyprint import HTML
from django.utils import timezone
from .models import Assignment

def generate_act_pdf(assignment):
    # Corrección: brand está vinculado al modelo, no directamente al activo
    active_assignments = Assignment.objects.filter(
        employee=assignment.employee, 
        status='ACTIVE'
    ).select_related('asset', 'asset__category', 'asset__model', 'asset__model__brand')
    
    context = {
        'company': assignment.asset.company,
        'site': assignment.asset.site,
        'area': assignment.employee.area,
        'employee': assignment.employee,
        'assignments': active_assignments,
        'assigned_by': assignment.assigned_by,
        'date': timezone.localtime(timezone.now()).strftime('%d de %B de %Y'),
        'observations': assignment.observations,
        'logo_acepalma': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_acepalma.png')}",
        'logo_solutrans': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_solutrans.png')}",
    }
    
    html_string = render_to_string('assignments/pdf_template.html', context)
    pdf_bytes = HTML(string=html_string).write_pdf()
    
    filename = f"Acta_{assignment.employee.document_number or '0000'}_{timezone.now().strftime('%Y%m%d%H%M')}.pdf"
    assignment.signed_act_pdf.save(filename, ContentFile(pdf_bytes), save=False)
    return assignment.signed_act_pdf
