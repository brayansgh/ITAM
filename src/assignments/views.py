from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied

from accounts.models import Role
from .models import Assignment


@staff_member_required
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

    if not assignment.signed_act_pdf:
        raise Http404(
            "El acta PDF no ha sido generada."
        )

    return FileResponse(
        assignment.signed_act_pdf.open("rb"),
        content_type="application/pdf",
    )
