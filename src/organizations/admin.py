from django.contrib import admin, messages
from django.utils.safestring import SafeString, mark_safe
from core.admin_audit import StandardHistoryAdmin
from .models import Company, Site, Area


@admin.register(Company)
class CompanyAdmin(StandardHistoryAdmin):
    list_display = ("name", "code", "status")
    search_fields = ("name", "code")
    list_filter = ("status",)

    def message_user(self, request, message, level=messages.INFO, extra_tags="", fail_silently=False):
        if level == messages.SUCCESS and isinstance(message, SafeString) and message.startswith("El Compañía “"):
            # Django ya escapó el nombre y construyó el enlace de la ficha.
            message = mark_safe(message.replace("El Compañía", "La compañía", 1))
        super().message_user(request, message, level, extra_tags, fail_silently)


@admin.register(Site)
class SiteAdmin(StandardHistoryAdmin):
    list_display = ("name", "city", "status")
    fields = ("name", "address", "city", "status")
    search_fields = ("name", "city")
    list_filter = ("status",)


@admin.register(Area)
class AreaAdmin(StandardHistoryAdmin):
    list_display = ("name", "company", "status")
    search_fields = ("name", "company__name")
    list_filter = ("status",)
