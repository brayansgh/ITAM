import os
import io
from datetime import datetime
from django.conf import settings
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.core.files.base import ContentFile
from weasyprint import HTML

def generate_and_save_offboarding_pdf(employee, assets, tech_user):
meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
now = datetime.now()
fecha_str = f"{now.day} de {meses[now.month - 1]} de {now.year}"

context = {
    'company': {'name': getattr(employee, 'company', 'SOLUTRANS')},
    'area': {'name': getattr(employee, 'department', getattr(employee, 'area', 'LOGISTICA'))},
    'site': {'name': getattr(employee, 'sede', getattr(employee, 'location', 'SANTA MARTA'))},
    'employee': employee,
    'assignments': [{'asset': a} for a in assets],
    'date': fecha_str,
    'assigned_by': tech_user,
    'checklist_items': [
        "Cambio de contraseñas de la cuenta de red en el Directorio Activo",
        "Bloqueo temporal del usuario en el Directorio Activo",
        "Cambiar el nombre de la cuenta de usuario como Disponible mas el nombre del cargo",
        "Verificar con Talento Humano el direccionamiento de correos hacia otro cargo",
        "Retirar el usuario propietario al equipo de cómputo en Intune",
        "Retiro de Licenciamiento de Defender for Endpoint",
        "Revoca los métodos de autenticación multifactor (MFA) registrados.",
        "Bloqueo de Usuario en SAP",
        "Se da por expirada la vigencia del usuario en SAP",
        "Retiro de Licenciamiento de SAP",
        "Retiro de Roles de SAP"
    ],
    # Rutas locales estrictas basadas en tu entorno
    'logo_acepalma': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_acepalma.png')}",
    'logo_solutrans': f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_solutrans.png')}",
}

html_string = render_to_string('assignments/offboarding_pdf.html', context)
buffer = io.BytesIO()
HTML(string=html_string).write_pdf(buffer)
pdf_data = buffer.getvalue()

# 1. Guardar en el perfil del empleado
doc_num = getattr(employee, 'document_number', getattr(employee, 'cedula', employee.id))
filename = f"Acta_Desvinculacion_{doc_num}.pdf"
if hasattr(employee, 'acta_desvinculacion'):
    employee.acta_desvinculacion.save(filename, ContentFile(pdf_data), save=True)
    
# 2. Retornar en línea (Abre en navegador, no descarga)
response = HttpResponse(pdf_data, content_type='application/pdf')
response['Content-Disposition'] = f'inline; filename="{filename}"'
return response
