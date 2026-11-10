"""Presentación común de auditoría; los códigos originales permanecen intactos."""
from datetime import date, datetime
from decimal import Decimal

from django.db import models
from django.utils import formats, timezone


IGNORED_FIELDS = {"id", "created_at", "updated_at", "last_login", "delivery_id"}
SENSITIVE_FIELDS = {"password"}
FIELD_LABELS = {
    "username": "Usuario", "first_name": "Nombres", "last_name": "Apellidos",
    "email": "Correo electrónico", "role": "Rol ITAM", "is_active": "Activo",
    "is_staff": "Acceso al administrador", "is_superuser": "Superusuario",
    "groups": "Grupos", "user_permissions": "Permisos individuales",
    "permissions": "Permisos", "name": "Nombre", "code": "Código",
    "asset_tag": "Código interno", "legacy_asset_tag": "Placa heredada",
    "serial_number": "Número de serie", "status": "Estado",
    "company": "Compañía", "owner_company": "Compañía propietaria", "site": "Sede",
    "area": "Área", "category": "Categoría", "model": "Modelo", "brand": "Marca",
    "asset": "Activo", "employee": "Empleado", "assigned_by": "Asignado por",
    "assigned_at": "Fecha de asignación", "returned_at": "Fecha de devolución",
    "initial_condition": "Condición de entrega", "return_condition": "Condición de devolución",
    "observations": "Observaciones", "signed_act_pdf": "Acta PDF",
    "document": "Documento", "pdf": "Acta PDF", "received_by": "Recibido por",
    "full_name": "Nombre completo", "document_type": "Tipo de documento",
    "document_number": "Número de documento", "phone": "Teléfono",
    "tax_id": "Identificación fiscal", "address": "Dirección", "city": "Ciudad",
    "type": "Tipo", "description": "Descripción", "cost": "Costo",
    "provider": "Proveedor", "reported_by": "Reportado por",
    "resolution_notes": "Notas de resolución", "property_type": "Tipo de propiedad",
    "purchase_date": "Fecha de compra", "warranty_end_date": "Fin de garantía",
    "date_joined": "Fecha de creación de cuenta", "maintenance": "Mantenimiento",
    "offboarding_record": "Acta de devolución", "assignment": "Asignación",
    "condition": "Condición", "sheet_name": "Hoja", "row_number": "Fila",
    "employee_name": "Nombre del empleado", "employee_document": "Documento del empleado",
    "element": "Elemento", "validation_notes": "Notas de validación",
    "storage": "Almacenamiento", "processor": "Procesador", "ram": "RAM",
    "operating_system": "Sistema operativo", "hostname": "Nombre del equipo",
    "mac_address": "Dirección MAC", "phone_number": "Número telefónico",
    "operator": "Operador", "warranty_start": "Inicio de garantía", "warranty_end": "Fin de garantía",
}
ACTION_LABELS = {"+": "Creación", "~": "Modificación", "-": "Eliminación"}


def format_value(field, value):
    # El permiso de mantenimiento no concede acceso a los datos del empleado del acta.
    if field is not None and field.name == "return_item":
        return "Acta de devolución vinculada" if value else "Sin dato"
    if isinstance(field, models.FileField):
        return "Archivo adjunto" if value else "Sin archivo"
    if value is None or value == "" or value == []:
        return "Sin dato"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if field is not None and field.choices:
        return str(dict(field.flatchoices).get(value, value))
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, Decimal):
        return formats.localize(value)
    if isinstance(value, list):
        # M2M: diff_against entrega una fila por relación, con objetos humanos.
        labels = []
        for row in value:
            target = field.remote_field.model if field is not None and field.many_to_many else models.Model
            objects = [str(item) for item in row.values() if isinstance(item, target)]
            labels.append(" / ".join(objects) if objects else ", ".join(str(item) for item in row.values()))
        return "; ".join(sorted(labels)) or "Sin dato"
    return str(value)


def version_row(record, previous, relations_since=None):
    changes = []
    excluded = set(IGNORED_FIELDS)
    note = "Separación de marca: copia exacta de la asociación del modelo legado." if record.history_change_reason == "Separación de marca: copia exacta de la asociación del modelo legado." else ""
    if previous is not None and relations_since is not None and previous.history_date < relations_since:
        excluded.update({"groups", "user_permissions"})
        note = "La versión anterior no incluye seguimiento completo de grupos y permisos; no se reconstruyen diferencias de esas relaciones."
    if previous is not None:
        delta = record.diff_against(
            previous, excluded_fields=excluded, foreign_keys_are_objs=True,
        )
        for change in delta.changes:
            if change.field in SENSITIVE_FIELDS:
                changes.append({"field": "Contraseña", "old": "*** (Anterior)", "new": "*** Modificada"})
                continue
            field = record.instance._meta.get_field(change.field)
            changes.append({
                "field": FIELD_LABELS.get(change.field, str(field.verbose_name).capitalize()),
                "old": format_value(field, change.old),
                "new": format_value(field, change.new),
            })
    if record.history_type == "+":
        detail = "Registro inicial."
    elif record.history_type == "-":
        detail = "Registro eliminado."
    elif previous is None:
        detail = "Sin versión anterior disponible; no se puede reconstruir el cambio."
    else:
        detail = "Sin cambios en los campos auditables."
    return {
        "date": record.history_date,
        "actor": record.history_user.get_display_name() if record.history_user else "Sin responsable registrado",
        "action": ACTION_LABELS[record.history_type],
        "code": record.history_type,
        "changes": changes,
        "detail": detail,
        "note": note,
    }


def current_actor(instance=None):
    """Usa un actor explícito o la petición real; no adivina un administrador."""
    explicit = getattr(instance, "_history_user", None) if instance is not None else None
    if explicit is not None:
        return explicit
    from simple_history.models import HistoricalRecords
    request = getattr(HistoricalRecords.context, "request", None)
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None
