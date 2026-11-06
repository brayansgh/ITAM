from django.contrib import admin
from core.admin_audit import StandardHistoryAdmin
from .models import Company, Site, Area


@admin.register(Company)
class CompanyAdmin(StandardHistoryAdmin):
    list_display = ("name", "code", "status")
    search_fields = ("name", "code")
    list_filter = ("status",)


@admin.register(Site)
class SiteAdmin(StandardHistoryAdmin):
    list_display = ("name", "company", "city", "status")
    search_fields = ("name", "city", "company__name")
    list_filter = ("status", "company")


@admin.register(Area)
class AreaAdmin(StandardHistoryAdmin):
    list_display = ("name", "company", "status")
    search_fields = ("name", "company__name")
    list_filter = ("status", "company")
