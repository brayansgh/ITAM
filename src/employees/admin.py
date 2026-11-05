from django.contrib import admin
from django.apps import apps
from django.utils.html import format_html
from .models import Employee

BaseAdmin = admin.ModelAdmin


@admin.register(Employee)
class EmployeeAdmin(BaseAdmin):

    search_fields = ("full_name", "document_number")

    list_display = (
        "full_name",
        "document_type",
        "company",
        "site",
        "area",
        "created_at",
        "view_assigned_assets"
    )

    def view_assigned_assets(self, obj):
        url = f"/admin/assignments/assignment/?employee__id__exact={obj.id}"

        return format_html(
            '<a class="button" style="background-color: #417690; color: white; padding: 5px 10px; border-radius: 4px;" href="{}">Ver Activos</a>',
            url
        )

    view_assigned_assets.short_description = "Activos Asignados"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        for field_name in ["status", "estado"]:
            if field_name in form.base_fields:
                field = form.base_fields[field_name]

                if hasattr(field, "choices"):
                    choices = list(field.choices)

                    if not any(c[0] == "RETIRO" for c in choices):
                        choices.append(("RETIRO", "Retiro de la compañía"))
                        field.choices = choices

        return form

    def response_change(self, request, obj):
        status_val = str(
            getattr(obj, "status", getattr(obj, "estado", ""))
        ).upper()

        if status_val == "RETIRO":
            try:
                from inventory.offboarding_pdf import generate_and_save_offboarding_pdf

                Asset = apps.get_model("inventory", "Asset")
                assets_liberados = []

                for asset in Asset.objects.exclude(
                    status__icontains="DECOMMISSION"
                ):
                    if (
                        getattr(asset, "employee", None) == obj
                        or getattr(asset, "assigned_to", None) == obj
                    ):
                        setattr(asset, "employee", None)
                        setattr(asset, "assigned_to", None)

                        if hasattr(asset, "status"):
                            asset.status = "AVAILABLE"

                        asset.save()
                        assets_liberados.append(asset)

                return generate_and_save_offboarding_pdf(
                    obj, assets_liberados, request.user
                )

            except Exception as e:
                self.message_user(
                    request,
                    f"Error al generar acta: {e}",
                    level="ERROR"
                )

        return super().response_change(request, obj)
