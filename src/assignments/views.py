from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache

from accounts.models import Role
from .models import Assignment


@staff_member_required
@never_cache
def download_act_pdf(request, assignment_id):

    user = request.user

    allowed_roles = (
        Role.ADMINISTRATOR,
        Role.TECHNOLOGY,
        Role.CONSULTATION,
    )

    if not (
        user.is_superuser
        or user.role in allowed_roles
    ):
        raise PermissionDenied(
            "No tienes permiso para consultar esta acta."
        )

    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
    )

    file_name = assignment.signed_act_pdf.name
    version = request.GET.get("version")
    if version is not None:
        if not version.isascii() or not version.isdecimal() or len(version) > 19:
            raise Http404
        historical = get_object_or_404(assignment.history, history_id=version)
        file_name = historical.signed_act_pdf

    if not file_name:
        raise Http404(
            "El acta PDF no ha sido generada."
        )

    try:
        pdf = assignment.signed_act_pdf.storage.open(file_name, "rb")
    except FileNotFoundError as error:
        raise Http404("El acta PDF no está disponible.") from error
    return FileResponse(
        pdf, content_type="application/pdf", filename="acta-de-entrega.pdf",
        as_attachment=request.GET.get("descargar") == "1",
    )
