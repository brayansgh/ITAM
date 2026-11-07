import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from weasyprint import HTML


def generate_and_save_offboarding_pdf(record):
    employee = record.employee

    # Obtener exclusivamente los activos de esta acta.
    items = record.items.select_related(
        "assignment__asset__category",
        "assignment__asset__brand",
    ).all()

    # Adaptar los datos al formato que espera la plantilla.
    assignments = [
        {
            "asset": item.assignment.asset,
            "condition": item.condition,
            "observations": item.observations,
        }
        for item in items
    ]

    # Fecha del registro.
    fecha = timezone.localtime(record.created_at)

    meses = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]

    fecha_str = (
        f"{fecha.day} de "
        f"{meses[fecha.month - 1]} de "
        f"{fecha.year}"
    )

    # Datos que recibirá la plantilla HTML.
    context = {
        "company": {
            "name": employee.company.name,
        },
        "area": {
            "name": employee.area.name if employee.area else "N/A",
        },
        "site": {
            "name": employee.site.name if employee.site else "N/A",
        },
        "employee": employee,
        "assignments": assignments,
        "date": fecha_str,
        "assigned_by": record.received_by,
        "observations": record.observations,
        "record": record,

        "checklist_items": [
            "Cambio de contraseñas de la cuenta de red en el Directorio Activo",
            "Bloqueo temporal del usuario en el Directorio Activo",
            "Cambiar el nombre de la cuenta de usuario como Disponible más el nombre del cargo",
            "Verificar con Talento Humano el direccionamiento de correos hacia otro cargo",
            "Retirar el usuario propietario al equipo de cómputo en Intune",
            "Retiro de Licenciamiento de Defender for Endpoint",
            "Revocar los métodos de autenticación multifactor (MFA) registrados",
            "Bloqueo de Usuario en SAP",
            "Se da por expirada la vigencia del usuario en SAP",
            "Retiro de Licenciamiento de SAP",
            "Retiro de Roles de SAP",
        ],

        "logo_acepalma": (
            f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_acepalma.png')}"
        ),

        "logo_solutrans": (
            f"file://{os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_solutrans.png')}"
        ),
    }

    # Renderizar HTML.
    html_string = render_to_string(
        "assignments/offboarding_pdf.html",
        context,
    )

    # Generar PDF en memoria.
    buffer = io.BytesIO()

    HTML(
        string=html_string,
        base_url=str(settings.BASE_DIR),
    ).write_pdf(buffer)

    pdf_data = buffer.getvalue()

    # Crear nombre único para cada acta.
    doc_num = employee.document_number or str(employee.pk)

    filename = (
        f"Acta_Devolucion_{doc_num}_{record.pk}.pdf"
    )

    # Guardar el PDF en el registro de devolución.
    record.pdf.save(
        filename,
        ContentFile(pdf_data),
        save=True,
    )

    # Mostrar el PDF en el navegador.
    response = HttpResponse(
        pdf_data,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{filename}"'
    )

    return response
