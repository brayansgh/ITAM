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
