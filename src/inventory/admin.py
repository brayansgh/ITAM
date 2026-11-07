from core.admin_audit import StandardHistoryAdmin
from django.contrib import admin
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode
from .models import Category, Brand, ModelAsset, Asset, AssetSpecs, AssetNetwork, AssetWarranty, DecommissionedAsset
from .forms import AssetRegistrationForm
from django.forms import modelform_factory

@admin.register(Category)
class CategoryAdmin(StandardHistoryAdmin):
    list_display = ('name', 'group', 'created_at')
    list_filter = ('group',)
    search_fields = ('name',)

@admin.register(Brand)
class BrandAdmin(StandardHistoryAdmin):
    list_display = ('name', 'associated_assets', 'created_at')
    search_fields = ('name',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        for key, model in (('active_assets', Asset), ('decommissioned_assets', DecommissionedAsset)):
            asset_admin = self.admin_site._registry[model]
            if not (asset_admin.has_module_permission(request) and asset_admin.has_view_permission(request)):
                continue
            counts = (asset_admin.get_queryset(request)
                      .filter(brand_id=OuterRef('pk')).order_by().values('brand_id')
                      .annotate(total=Count('pk', distinct=True)).values('total'))
            queryset = queryset.annotate(**{key: Coalesce(Subquery(counts), 0)})
        return queryset

    @admin.display(description='Activos visibles')
    def associated_assets(self, obj):
        links = []
        total = 0
        for key, label, route in (
            ('active_assets', 'Ver vigentes', 'admin:inventory_asset_changelist'),
            ('decommissioned_assets', 'Ver bajas', 'admin:inventory_decommissionedasset_changelist'),
        ):
            count = getattr(obj, key, None)
            if count is not None:
                total += count
                url = reverse(route) + '?' + urlencode({'brand__id__exact': obj.pk})
                links.append((url, label, count))
        if not links:
            return 'Sin permiso para consultar activos'
        actions = format_html_join('', '<a href="{}" class="button">{} ({})</a>', links)
        return format_html('<div class="itam-brand-assets"><strong>{}</strong>{}</div>', total, actions)

@admin.register(ModelAsset)
class ModelAssetAdmin(StandardHistoryAdmin):
    list_display = ('name', 'created_at')
    fields = ('name',)
    search_fields = ('name',)

class FrozenAssetInlineMixin:
    def has_add_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.status == "DECOMMISSIONED") and super().has_delete_permission(request, obj)


class AssetSpecsInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetSpecs
    verbose_name = 'Información técnica'
    verbose_name_plural = 'Información técnica'
    form = modelform_factory(AssetSpecs, fields='__all__', labels={'ram': 'Memoria RAM', 'storage': 'Almacenamiento', 'processor': 'Procesador', 'operating_system': 'Sistema operativo'})
    can_delete = False

class AssetNetworkInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetNetwork
    verbose_name = 'Red y telefonía'
    verbose_name_plural = 'Red y telefonía'
    form = modelform_factory(AssetNetwork, fields='__all__', labels={'hostname': 'Hostname', 'mac_address': 'Dirección MAC', 'imei': 'IMEI', 'phone_number': 'Número de teléfono', 'operator': 'Operador'})
    can_delete = False

class AssetWarrantyInline(FrozenAssetInlineMixin, admin.StackedInline):
    model = AssetWarranty
    verbose_name = 'Garantía y compra'
    verbose_name_plural = 'Garantías y compra'
    form = modelform_factory(AssetWarranty, fields='__all__', labels={'supplier': 'Proveedor', 'warranty_start': 'Inicio de garantía', 'warranty_end': 'Fin de garantía'})
    extra = 0

@admin.register(Asset)
class AssetAdmin(StandardHistoryAdmin):
    form = AssetRegistrationForm
    list_per_page = 25
    fieldsets = (
        ('Clasificación', {'fields': ('group', 'category')}),
        ('Identificación y propiedad', {'fields': ('legacy_asset_tag', 'asset_tag', 'owner_company', 'brand', 'model', 'serial_number', 'property_type')}),
        ('Administración y ubicación', {'fields': ('company', 'site')}),
        ('Información adicional', {'fields': ('status', 'purchase_date', 'warranty_end_date', 'observations')}),
    )
    list_display = ('asset_tag', 'category', 'brand_model', 'serial_number', 'company', 'status')
    list_filter = ('company', 'site', 'category__group', 'category', 'brand', 'status', 'property_type')
    search_fields = ('asset_tag', 'legacy_asset_tag', 'serial_number', 'network__hostname', 'current_employee_name')
    change_form_template = 'admin/inventory/asset/change_form.html'
    inlines = [AssetSpecsInline, AssetNetworkInline, AssetWarrantyInline]
    audit_related_models = ((AssetSpecs, "asset"), (AssetNetwork, "asset"), (AssetWarranty, "asset"))

    def get_search_fields(self, request):
        fields = super().get_search_fields(request)
        if getattr(request, 'user', None):
            from assignments.models import Assignment
            if not self.admin_site._registry[Assignment].has_view_permission(request):
                return tuple(field for field in fields if field != 'current_employee_name')
        return fields
    
    def get_queryset(self, request):
        from assignments.models import Assignment, AssignmentStatus
        active = Assignment.objects.filter(asset_id=OuterRef("pk"), status=AssignmentStatus.ACTIVE)
        return super().get_queryset(request).select_related(
            "category", "brand", "model", "company", "owner_company", "site",
        ).annotate(current_employee_name=Subquery(active.values("employee__full_name")[:1]))

    def get_urls(self):
        from django.urls import path
        return [path('tipos/', self.admin_site.admin_view(self.category_options), name='inventory_category_options')] + super().get_urls()

    def category_options(self, request):
        from django.core.exceptions import PermissionDenied
        from django.http import JsonResponse
        if not (self.has_view_permission(request) or self.has_add_permission(request)):
            raise PermissionDenied
        return JsonResponse({'results': list(Category.objects.filter(group=request.GET.get('group', '')).exclude(group='').order_by('name').values('id', 'name'))})

    def get_readonly_fields(self, request, obj=None):
        return ('asset_tag', 'owner_company') if obj else ('asset_tag',)

    @admin.display(description='Activo', ordering='legacy_asset_tag')
    def asset_identity(self, obj):
        return format_html('<strong>{}</strong><br><span class="itam-secondary">{}</span>', obj.display_identifier, obj.asset_tag if obj.legacy_asset_tag else 'Sin placa de activo fijo')

    @admin.display(description='Clasificación', ordering='category__group')
    def classification(self, obj):
        return format_html('<span class="itam-label">{}</span><br><span class="itam-secondary">{}</span>', obj.category.get_group_display() or 'Sin grupo (legado)', obj.category.name)

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
            context['asset_detail'] = request.method == 'GET' and request.GET.get('editar') != '1'
            context['asset_edit_url'] = request.path + '?editar=1'
            context['can_asset_specs'] = AssetSpecsInline(self.model, self.admin_site).has_view_permission(request, obj)
            context['can_asset_network'] = AssetNetworkInline(self.model, self.admin_site).has_view_permission(request, obj)
            from maintenance.models import MaintenanceRecord, MaintenanceDocument
            from assignments.models import Assignment
            ma = self.admin_site._registry[MaintenanceRecord]
            aa = self.admin_site._registry[Assignment]
            documents = []
            if aa.has_view_permission(request):
                for assignment in aa.get_queryset(request).filter(asset=obj).exclude(signed_act_pdf='').exclude(signed_act_pdf__isnull=True):
                    if aa.has_view_permission(request, assignment):
                        documents.append({'label': 'Acta de asignación', 'url': reverse('download_act_pdf', args=[assignment.pk])})
            if ma.has_view_permission(request):
                tickets = ma.get_queryset(request).filter(asset=obj)
                for document in MaintenanceDocument.objects.filter(maintenance__in=tickets).select_related('maintenance'):
                    if ma.has_view_permission(request, document.maintenance):
                        documents.append({'label': 'Evidencia de ticket', 'url': reverse('admin:maintenance_document_download', args=[document.pk])})
            context['asset_documents'] = documents
            context['asset_tickets'] = ma.get_queryset(request).filter(asset=obj).select_related('reported_by')[:20] if ma.has_view_permission(request) else []
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
        return " · ".join(value for value in (
            obj.brand.name if obj.brand else "", obj.model.name if obj.model else "",
        ) if value) or "-"
    brand_model.short_description = "Marca y Modelo"
    class Media:
        js = ('js/hide_change_reason.js', 'itam/asset-form.js')

# --- SEPARACIÓN DEL CEMENTERIO DE ACTIVOS ---
from django.apps import apps

if Asset in admin.site._registry:
    OriginalAssetAdmin = type(admin.site._registry[Asset])
    admin.site.unregister(Asset)
    
    class ActiveAssetAdmin(OriginalAssetAdmin):
        list_display = (
            'asset_identity', 'classification', 'brand_model', 'company', 'site', 'assigned_employee', 'status',
        )

        def get_queryset(self, request):
            return super().get_queryset(request).exclude(status__icontains="DECOMMISSION")

        def get_list_display(self, request):
            columns = super().get_list_display(request)
            if getattr(request, 'user', None):
                from assignments.models import Assignment
                if not self.admin_site._registry[Assignment].has_view_permission(request):
                    @admin.display(description='Custodio')
                    def restricted_custodian(obj):
                        return 'Sin permiso para consultar custodia'
                    return tuple(restricted_custodian if column == 'assigned_employee' else column for column in columns)
            return columns

        @admin.display(description="Asignado a", ordering="current_employee_name")
        def assigned_employee(self, obj):
            return obj.current_employee_name or "Sin asignación"
            
    admin.site.register(Asset, ActiveAssetAdmin)

@admin.register(DecommissionedAsset)
class DecommissionedAssetAdmin(OriginalAssetAdmin):
    change_form_template = "admin/inventory/decommissionedasset/change_form.html"
    list_display = ('asset_identity', 'classification', 'brand_model', 'company', 'site', 'status')
    
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
