from core.admin_audit import StandardHistoryAdmin
from django.contrib import admin
from django.db.models import OuterRef, Subquery
from django.urls import reverse
from .models import Category, Brand, ModelAsset, Asset, AssetSpecs, AssetNetwork, AssetWarranty

@admin.register(Category)
class CategoryAdmin(StandardHistoryAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Brand)
class BrandAdmin(StandardHistoryAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(ModelAsset)
class ModelAssetAdmin(StandardHistoryAdmin):
    list_display = ('name', 'brand', 'category')
    list_filter = ('brand', 'category')
    search_fields = ('name', 'brand__name')

class FrozenAssetInlineMixin:
    def has_add_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_delete_permission(request, obj)


class AssetSpecsInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetSpecs
    can_delete = False

class AssetNetworkInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetNetwork
    can_delete = False

class AssetWarrantyInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetWarranty
    extra = 0

@admin.register(Asset)
class AssetAdmin(StandardHistoryAdmin):
    list_display = ('asset_tag', 'category', 'brand_model', 'serial_number', 'company', 'status')
    list_filter = ('status', 'property_type', 'company', 'site', 'category')
    search_fields = ('asset_tag', 'legacy_asset_tag', 'serial_number', 'network__hostname', 'current_employee_name')
    change_form_template = 'admin/inventory/asset/change_form.html'
    inlines = [AssetSpecsInline, AssetNetworkInline, AssetWarrantyInline]
    audit_related_models = ((AssetSpecs, "asset"), (AssetNetwork, "asset"), (AssetWarranty, "asset"))
    
    def get_queryset(self, request):
        from assignments.models import Assignment, AssignmentStatus
        active = Assignment.objects.filter(asset_id=OuterRef("pk"), status=AssignmentStatus.ACTIVE)
        return super().get_queryset(request).select_related(
            "category", "model__brand", "company", "owner_company", "site",
        ).annotate(current_employee_name=Subquery(active.values("employee__full_name")[:1]))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for name, label in (("company", "Compañía administradora"), ("owner_company", "Compañía propietaria"),
                            ("site", "Ciudad / ubicación física")):
            if name in form.base_fields:
                form.base_fields[name].label = label
        if "site" in form.base_fields:
            form.base_fields["site"].help_text = "Ubicación física del activo; no requiere asociación con una compañía."
        return form

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            from .timeline import asset_timeline
            context["asset_timeline"] = asset_timeline(request, obj, self.admin_site)
            context["asset_audit_url"] = reverse(
                f"admin:inventory_{self.model._meta.model_name}_history", args=[obj.pk],
            )
            context["asset_record"] = obj
        return super().render_change_form(request, context, add, change, form_url, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status == "DECOMMISSIONED":
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == "DECOMMISSIONED":
            return False
        return super().has_delete_permission(request, obj)

    def brand_model(self, obj):
        if obj.model:
            return f"{obj.model.brand.name} {obj.model.name}"
        return "-"
    brand_model.short_description = "Marca y Modelo"
    class Media:
        js = ('js/hide_change_reason.js',)

# --- SEPARACIÓN DEL CEMENTERIO DE ACTIVOS ---
from django.utils.html import format_html
from django.apps import apps
from .models import Asset, DecommissionedAsset

if Asset in admin.site._registry:
    OriginalAssetAdmin = type(admin.site._registry[Asset])
    admin.site.unregister(Asset)
    
    class ActiveAssetAdmin(OriginalAssetAdmin):
        list_display = (
            'legacy_asset_tag', 'assigned_employee', 'brand_model',
            'serial_number', 'company', 'status',
        )

        def get_queryset(self, request):
            return super().get_queryset(request).exclude(status__icontains="DECOMMISSION")

        @admin.display(description="Asignado a", ordering="current_employee_name")
        def assigned_employee(self, obj):
            return obj.current_employee_name or "Sin asignación"
            
    admin.site.register(Asset, ActiveAssetAdmin)

@admin.register(DecommissionedAsset)
class DecommissionedAssetAdmin(OriginalAssetAdmin):
    change_form_template = "admin/inventory/decommissionedasset/change_form.html"
    
    def get_queryset(self, request):
        return super().get_queryset(request).filter(status__icontains="DECOMMISSION")
        
    def has_add_permission(self, request):
        return False 

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def ciclo_de_vida(self, obj):
        from django.template.loader import render_to_string
        from django.utils.safestring import mark_safe
        from maintenance.models import MaintenanceRecord

        # Solo se marca como seguro el resultado de una plantilla con autoescape.
        return mark_safe(render_to_string(
            "admin/inventory/decommissionedasset/lifecycle.html",
            {
                "maintenances": MaintenanceRecord.objects.filter(asset=obj)
                    .select_related("reported_by").order_by("-created_at", "-pk"),
                "assignments": obj.assignments.select_related("employee")
                    .order_by("-assigned_at", "-pk"),
            },
        ))
    ciclo_de_vida.short_description = ""

# La identidad del administrador se conserva; el historial se presenta en core.
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from accounts.admin import AccountUserAdminMixin, AccountGroupAdminMixin

User = get_user_model()


class AuditedUserAdmin(AccountUserAdminMixin, StandardHistoryAdmin, UserAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(super().get_readonly_fields(request, obj)) + ("last_login", "date_joined")


class AuditedGroupAdmin(AccountGroupAdminMixin, StandardHistoryAdmin, GroupAdmin):
    pass


for model in (User, Group):
    if admin.site.is_registered(model):
        admin.site.unregister(model)
admin.site.register(User, AuditedUserAdmin)
admin.site.register(Group, AuditedGroupAdmin)
