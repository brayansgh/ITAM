"""Coherencia de relaciones organizativas sin reasignar datos implícitamente."""
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import router, transaction


def validate_company_links(instance, using=None, values=None, lock=False):
    using = using or instance._state.db or router.db_for_write(type(instance), instance=instance)
    values = values or {name: getattr(instance, name + "_id") for name in
                        ("company", "site", "area") if hasattr(instance, name + "_id")}
    company_id = values.get("company")
    if company_id is None:
        return
    errors = {}
    for field, model in (("site", "Site"), ("area", "Area")):
        # En activos, la sede es ubicación física compartida entre compañías.
        if field == "site" and instance._meta.concrete_model._meta.label_lower == "inventory.asset":
            continue
        related_id = values.get(field)
        if related_id is None:
            continue
        qs = apps.get_model("organizations", model).objects.using(using)
        if lock:
            qs = qs.select_for_update()
        parent = qs.filter(pk=related_id).values_list("company_id", flat=True).first()
        if parent is not None and parent != company_id:
            errors[field] = "Debe pertenecer a la compañía del registro."
    if errors:
        raise ValidationError(errors)


def save_with_company_links(instance, save, *args, **kwargs):
    using = kwargs.get("using") or router.db_for_write(type(instance), instance=instance)
    fields = kwargs.get("update_fields")
    names = [name for name in ("company", "site", "area") if hasattr(instance, name + "_id")]
    with transaction.atomic(using=using):
        if fields is None or any(name in fields or name + "_id" in fields for name in names):
            previous = type(instance).objects.using(using).select_for_update().filter(pk=instance.pk).values(
                *(name + "_id" for name in names)
            ).first()
            values = {name: getattr(instance, name + "_id") if fields is None or name in fields or name + "_id" in fields or previous is None
                      else previous[name + "_id"] for name in names}
            validate_company_links(instance, using, values=values, lock=True)
        return save(*args, **kwargs)


def validate_container_company(instance, using=None, company_id=None):
    using = using or instance._state.db or router.db_for_write(type(instance), instance=instance)
    company_id = company_id or instance.company_id
    if company_id is None or instance.pk is None:
        return
    previous = type(instance).objects.using(using).filter(pk=instance.pk).values_list("company_id", flat=True).first()
    if previous == company_id:
        return
    field = "site" if instance._meta.model_name == "site" else "area"
    references = [("employees", "Employee")]
    for app, model in references:
        if apps.get_model(app, model).objects.using(using).filter(
            **{field + "_id": instance.pk}
        ).exclude(company_id=company_id).exists():
            raise ValidationError({"company": "No se puede cambiar de compañía mientras existan registros vinculados de otra compañía."})


def save_container(instance, save, *args, **kwargs):
    using = kwargs.get("using") or router.db_for_write(type(instance), instance=instance)
    with transaction.atomic(using=using):
        type(instance).objects.using(using).select_for_update().filter(pk=instance.pk).first()
        fields = kwargs.get("update_fields")
        if fields is None or "company" in fields or "company_id" in fields:
            validate_container_company(instance, using)
        return save(*args, **kwargs)
