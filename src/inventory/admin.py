from django.contrib import admin
from .models import Category, Brand, Model, Asset, AssetSpecs, AssetNetwork, AssetWarranty

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Model)
class ModelAdmin(admin.ModelAdmin):
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
