from django.contrib import admin
from .models import Category, Brand, ModelAsset, Asset, AssetSpecs, AssetNetwork, AssetWarranty

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(ModelAsset)
class ModelAssetAdmin(admin.ModelAdmin):
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
class AssetAdmin(admin.ModelAdmin):
    list_display = ('asset_tag', 'category', 'brand_model', 'serial_number', 'company', 'status')
    list_filter = ('status', 'property_type', 'company', 'site', 'category')
    search_fields = ('asset_tag', 'legacy_asset_tag', 'serial_number')
    inlines = [AssetSpecsInline, AssetNetworkInline, AssetWarrantyInline]
    
    def brand_model(self, obj):
        if obj.model:
            return f"{obj.model.brand.name} {obj.model.name}"
        return "-"
    brand_model.short_description = "Marca y Modelo"
    class Media:
        js = ('js/hide_change_reason.js',)

    def save_model(self, request, obj, form, change):
        if change:
            changes = []
            for field in form.changed_data:
                old_val = form.initial.get(field)
                new_val = form.cleaned_data.get(field)
                field_name = obj._meta.get_field(field).verbose_name.title()
                changes.append(f"{field_name}: {old_val} ➔ {new_val}")
            
            if changes:
                change_message = " | ".join(changes)
                # Django's default history system looks for a specific format
                # We inject our custom message directly into the history log
                from django.contrib.admin.models import LogEntry, CHANGE
                from django.contrib.contenttypes.models import ContentType
                
                super().save_model(request, obj, form, change)
                
                LogEntry.objects.log_action(
                    user_id=request.user.pk,
                    content_type_id=ContentType.objects.get_for_model(obj).pk,
                    object_id=obj.pk,
                    object_repr=str(obj),
                    action_flag=CHANGE,
                    change_message=change_message,
                )
                return
        
        super().save_model(request, obj, form, change)

# --- SEPARACIÓN DEL CEMENTERIO DE ACTIVOS ---
from django.utils.html import format_html
from django.apps import apps
from .models import Asset, DecommissionedAsset

if Asset in admin.site._registry:
    OriginalAssetAdmin = type(admin.site._registry[Asset])
    admin.site.unregister(Asset)
    
    class ActiveAssetAdmin(OriginalAssetAdmin):
        def get_queryset(self, request):
            qs = super().get_queryset(request)
            return qs.exclude(status__icontains="DECOMMISSION")
            
    admin.site.register(Asset, ActiveAssetAdmin)

@admin.register(DecommissionedAsset)
class DecommissionedAssetAdmin(OriginalAssetAdmin):
    change_form_template = "admin/inventory/decommissionedasset/change_form.html"
    
    def get_queryset(self, request):
        return super(OriginalAssetAdmin, self).get_queryset(request).filter(status__icontains="DECOMMISSION")
        
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
        fieldsets.insert(0, ("Trazabilidad Histórica Global", {"fields": ("ciclo_de_vida",)}))
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
        from django.utils.html import format_html
        from django.apps import apps
        
        html = '<div style="padding: 15px; background-color: #2b2b2b; color: #f8f9fa; border-left: 4px solid #dc3545; border-radius: 4px; margin-bottom: 5px;">'
        html += '<h4 style="margin-top:0;">🛠️ Historial de Mantenimientos y Novedades</h4><ul style="margin-bottom:15px;">'
        try:
            MaintenanceRecord = apps.get_model("maintenance", "MaintenanceRecord")
            m_records = MaintenanceRecord.objects.filter(asset=obj).order_by("-id")
            if m_records.exists():
                for m in m_records:
                    html += f"<li>[{m.get_type_display()}] <b>{m.get_status_display()}</b> | Resp: {m.reported_by} | {m.description}</li>"
            else:
                html += "<li>Sin mantenimientos registrados.</li>"
        except Exception:
            pass
        html += "</ul>"

        html += '<h4>👤 Historial de Asignaciones (Usuarios)</h4><ul style="margin-bottom:0px;">'
        has_assign = False
        for rel in obj._meta.related_objects:
            accessor = rel.get_accessor_name()
            if accessor and any(k in accessor.lower() for k in ["assign", "asignacion"]):
                manager = getattr(obj, accessor, None)
                if manager:
                    for a in manager.all():
                        has_assign = True
                        target = getattr(a, 'employee', getattr(a, 'user', getattr(a, 'location', getattr(a, 'assigned_to', str(a).split('->')[-1]))))
                        html += f"<li>Asignado a: <b>{target}</b> <span style='color:#dc3545;'>[Cerrado permanentemente por Baja]</span></li>"
        if not has_assign:
            html += "<li>Sin asignaciones previas.</li>"
        html += "</ul></div>"
        
        return format_html(html)
    ciclo_de_vida.short_description = ""
