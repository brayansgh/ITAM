from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import Asset, AssetStatus, DecommissionedAsset


def asset_link(request, asset, site):
    model = DecommissionedAsset if asset.status == AssetStatus.DECOMMISSIONED else Asset
    target = site._registry[model]
    label = f"{asset.legacy_asset_tag} · {asset.asset_tag}" if asset.legacy_asset_tag else asset.asset_tag
    if not target.has_view_permission(request, asset):
        return label
    return format_html('<a href="{}">{}</a>', reverse(
        f"admin:inventory_{model._meta.model_name}_change", args=[asset.pk],
    ), label)


class AssetLinkAdminMixin:
    def get_list_display(self, request):
        @admin.display(description="Activo")
        def asset_detail(obj):
            return asset_link(request, obj.asset, self.admin_site)
        return tuple(asset_detail if field == "asset" else field for field in super().get_list_display(request))

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("asset__category")
