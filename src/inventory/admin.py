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

class AssetSpecsInline(admin.StackedInline):
    model = AssetSpecs
    can_delete = False

class AssetNetworkInline(admin.StackedInline):
    model = AssetNetwork
    can_delete = False

class AssetWarrantyInline(admin.StackedInline):
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

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if obj is not None:
            from .timeline import asset_timeline
            context["asset_timeline"] = asset_timeline(request, obj, self.admin_site)
            context["asset_audit_url"] = reverse(
                f"admin:inventory_{self.model._meta.model_name}_history", args=[obj.pk],
            )
            context["asset_record"] = obj
        return super().render_change_form(request, context, add, change, form_url, obj)

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

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        custom_fields = ["ciclo_de_vida"]
        if request.GET.get("force_edit") != "1":
            fields = [f.name for f in self.model._meta.fields if f.name != "id"]
            return list(set(readonly + fields + custom_fields))
        return list(set(readonly + custom_fields))

    def get_inline_instances(self, request, obj=None):
        inline_instances = super().get_inline_instances(request, obj)
        if request.GET.get("force_edit") != "1":
            for inline in inline_instances:
                # Asegurar que el anexo siempre sea visible aunque no tenga datos
                inline.extra = 1 if getattr(inline, 'extra', 0) == 0 else inline.extra
                inline.can_delete = False
                inline.has_add_permission = lambda request, obj=None: True
                inline.has_delete_permission = lambda request, obj=None: False
                
                # Fábrica para evitar el bug de mezcla de datos de Python
                def make_disabled_formset(orig_formset):
                    def get_disabled_formset(req, object=None, **kwargs):
                        fs = orig_formset(req, object, **kwargs)
                        class DisabledFS(fs):
                            def add_fields(self, form, index):
                                super().add_fields(form, index)
                                for name, field in form.fields.items():
                                    field.disabled = True
                        return DisabledFS
                    return get_disabled_formset
                
                inline.get_formset = make_disabled_formset(inline.get_formset)
        return inline_instances

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        for fs in fieldsets:
            fields_list = list(fs[1].get("fields", []))
            for f_name in ["boton_edicion_manual", "ciclo_de_vida"]:
                if f_name in fields_list:
                    fields_list.remove(f_name)
            fs[1]["fields"] = tuple(fields_list)

        fieldsets = [fs for fs in fieldsets if fs[0] not in ("Acciones (Solo Lectura)", "Trazabilidad Histórica Global")]
        return fieldsets

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if request.GET.get("force_edit") != "1":
            extra_context["show_save"] = False
            extra_context["show_save_and_continue"] = False
            extra_context["show_save_and_add_another"] = False
            extra_context["show_delete"] = False
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

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
