from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from .models import Assignment

@staff_member_required
def download_act_pdf(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not assignment.signed_act_pdf:
        raise Http404("El acta PDF no ha sido generada.")
    
    # Entrega el archivo como un flujo binario seguro sin exponer la ruta real
    return FileResponse(
        assignment.signed_act_pdf.open('rb'), 
        content_type='application/pdf'
    )
