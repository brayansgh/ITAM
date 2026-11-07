from django import template
from django.urls import reverse
from django.utils.text import Truncator

register = template.Library()


@register.inclusion_tag("admin/itam/breadcrumbs.html", takes_context=True)
def itam_breadcrumbs(context):
    request = context.get("request")
    route = getattr(getattr(request, "resolver_match", None), "url_name", None)
    if context.get("is_popup") or route == "index":
        return {}

    opts = context.get("opts")
    title = context.get("title")
    module = None
    allowed_urls = {
        model.get("admin_url")
        for app in context.get("available_apps", ())
        for model in app["models"]
    }
    if route in ("maintenance_decommission_add", "maintenance_decommission_change") or context.get("is_decommission"):
        module = "Bajas"
        maintenance_list = reverse("admin:maintenance_maintenancerecord_changelist")
        module_url = reverse("admin:itam_decommissions") if maintenance_list in allowed_urls else None
    elif opts:
        key = opts.label_lower
        module = context.get("itam_model_labels", {}).get(key, opts.verbose_name_plural)
        model_route = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        module_url = model_route if model_route in allowed_urls else None

    crumbs = []
    if module:
        if route and route.endswith("_changelist"):
            crumbs.append((module, None))
        else:
            crumbs.append((module, module_url))
            if context.get("change") and context.get("original"):
                title = Truncator(context["original"]).words(18)
            elif context.get("add") and not context.get("is_decommission"):
                title = "Añadir registro"
            if title:
                crumbs.append((title, None))
    elif title:
        crumbs.append((title, None))

    return {"crumbs": crumbs}
