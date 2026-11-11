from datetime import date
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from simple_history.utils import bulk_create_with_history

from assignments.services import create_assignment
from employees.models import Employee, EmployeeStatus
from employees.validation import validate_assignment_recipient
from inventory.models import Asset, AssetNetwork, AssetSpecs, AssetStatus, AssetWarranty, Brand, Category, ModelAsset
from organizations.models import Area, Company, Site

from .models import ImportStatus, StagingAsset
from .workbook import ASSETS, EMPLOYEES, ROW_FORMS, read_workbook


def one_record(queryset, label):
    records = list(queryset[:2])
    if len(records) != 1:
        reason = "tiene varias coincidencias" if records else "no existe en el catálogo"
        raise ValidationError(f"{label}: {reason}. Revisa el valor en la plantilla.")
    return records[0]


def company_by_code(code, label):
    return one_record(Company.objects.filter(code__iexact=code), label)


def named_record(queryset, name, label):
    if not name:
        return None
    if name.endswith("]") and " [" in name:
        try:
            identifier = UUID(name.rsplit(" [", 1)[1][:-1])
        except ValueError:
            pass
        else:
            return one_record(queryset.filter(pk=identifier), label)
    return one_record(queryset.filter(name__iexact=name), label)


def form_data(row):
    form = ROW_FORMS[row.sheet_name](row.workbook_data)
    if not form.is_valid():
        raise ValidationError([
            f"{form.fields[key].label}: {error}" for key, errors in form.errors.items() for error in errors
        ])
    return form.cleaned_data


def workbook_rows(row, sheet_name):
    return StagingAsset.objects.filter(batch_id=row.batch_id, sheet_name=sheet_name).exclude(
        status=ImportStatus.REJECTED,
    )


def employee_for_row(row, data):
    candidates = workbook_rows(row, EMPLOYEES).filter(employee_document__iexact=data["document_number"])
    if candidates.exclude(pk=row.pk).exists():
        raise ValidationError("El documento se repite en Empleados. Descarta la fila duplicada o corrige el Excel.")
    company = company_by_code(data["company"], "Compañía del empleado")
    site = named_record(Site.objects.all(), data["site"], "Sede del empleado")
    area = named_record(Area.objects.filter(company=company), data["area"], "Área del empleado")
    matches = Employee.objects.filter(document_number__iexact=data["document_number"])
    if matches.exists():
        employee = one_record(matches, "Documento del empleado")
        values = {
            "document_type": data["document_type"], "full_name": data["full_name"], "company": company,
            "site": site, "area": area, "email": data["email"], "phone": data["phone"], "status": data["status"],
        }
        differences = [
            ROW_FORMS[EMPLOYEES].base_fields[key].label for key, value in values.items()
            if value and getattr(employee, key) != value
        ]
        if differences:
            raise ValidationError(f"El empleado existente difiere en {', '.join(differences)}. Revisa su ficha antes de continuar.")
        return employee

    employee = Employee(
        document_number=data["document_number"], document_type=data["document_type"],
        full_name=data["full_name"], company=company, site=site, area=area,
        email=data["email"] or None, phone=data["phone"] or None, status=data["status"] or EmployeeStatus.ACTIVE,
    )
    employee.full_clean()
    return employee


def asset_custodian(row, document, *, publishing):
    if not document:
        return None
    candidates = list(workbook_rows(row, EMPLOYEES).filter(employee_document__iexact=document)[:2])
    if len(candidates) > 1:
        raise ValidationError("El documento del custodio corresponde a varias filas de Empleados.")
    if candidates:
        candidate = candidates[0]
        if publishing and candidate.status != ImportStatus.IMPORTED:
            raise ValidationError("Publica primero la fila del custodio o inclúyela aprobada en la misma selección.")
        employee = employee_for_row(candidate, form_data(candidate))
    else:
        matches = Employee.objects.filter(document_number__iexact=document)
        if not matches.exists():
            raise ValidationError("El custodio debe existir en ITAM o estar incluido en Empleados del mismo libro.")
        employee = one_record(matches, "Documento del custodio")
    if publishing and employee._state.adding:
        raise ValidationError("No se encontró al custodio en producción. Revisa su ficha antes de publicar el activo.")
    validate_assignment_recipient(employee)
    return employee


def asset_for_row(row, data, *, publishing):
    duplicates = workbook_rows(row, ASSETS).exclude(pk=row.pk)
    for field, label in (("legacy_asset_tag", "Placa"), ("serial_number", "Serie"),
                         ("import_reference", "Referencia de carga")):
        value = getattr(row, field)
        if not value:
            continue
        if duplicates.filter(**{field: value}).exists():
            raise ValidationError(f"{label} repetida en Activos. Descarta la fila duplicada o corrige el Excel.")
        published = StagingAsset.objects.filter(status=ImportStatus.IMPORTED) if field == "import_reference" else Asset.objects.all()
        if published.filter(**{field: value}).exists():
            raise ValidationError(f"{label} ya publicada. Revisa si el activo ya existe en ITAM.")

    company = company_by_code(data["company"], "Compañía administradora")
    owner = company_by_code(data["owner_company"], "Compañía propietaria")
    category = named_record(Category.objects.exclude(group=""), data["category"], "Tipo de activo")
    brand = named_record(Brand.objects.all(), data["brand"], "Marca")
    model = named_record(ModelAsset.objects.filter(brand=brand), data["model"], "Modelo de la marca")
    site = named_record(Site.objects.all(), data["site"], "Ubicación física")
    employee = asset_custodian(row, data["employee_document"], publishing=publishing)
    if data["due_on"] and data["due_on"] < timezone.localdate():
        raise ValidationError("La devolución prevista debe ser hoy o una fecha futura.")
    asset = Asset(
        legacy_asset_tag=data["legacy_asset_tag"] or None, serial_number=data["serial_number"] or None,
        company=company, owner_company=owner, category=category, brand=brand, model=model, site=site,
        property_type=data["property_type"], status=data["status"] or AssetStatus.AVAILABLE,
        purchase_date=data["purchase_date"], warranty_end_date=data["warranty_end_date"],
        observations=data["observations"] or None,
    )
    asset.full_clean(exclude=["asset_tag"])
    return asset, employee


def validate_row(row):
    data = form_data(row)
    if row.sheet_name == EMPLOYEES:
        employee_for_row(row, data)
    else:
        asset_for_row(row, data, publishing=False)


def update_review(row, *, actor, status=None, notes=""):
    status = status or row.status
    if (row.status, row.validation_notes or "") == (status, notes):
        return
    row.status, row.validation_notes = status, notes
    row._history_user = actor
    row.save(update_fields=["status", "validation_notes", "updated_at"])


def review_error(error):
    return "\n".join(error.messages)


def summary_value(model_field, value):
    if value is None:
        return None
    return str(value)[:StagingAsset._meta.get_field(model_field).max_length]


def workbook_values(sheet, data):
    summary = {
        "employee_name": data.get("full_name"),
        "employee_document": data.get("document_number") if sheet == EMPLOYEES else data.get("employee_document"),
        "element": data.get("category"),
        **{key: data.get(key) for key in ("legacy_asset_tag", "serial_number", "company", "site", "area")},
    }
    reference = data.get("import_reference")
    return {
        "workbook_data": data,
        "import_reference": reference.casefold()[:100] if isinstance(reference, str) else "",
        **{key: summary_value(key, value) for key, value in summary.items()},
    }


def staging_row(batch, sheet, number, data):
    return StagingAsset(batch_id=batch, sheet_name=sheet, row_number=number, **workbook_values(sheet, data))


@transaction.atomic
def save_review_edit(queryset, *, data, version, actor):
    row = queryset.select_for_update().first()
    if row is None or not row.batch_id or row.status == ImportStatus.IMPORTED:
        raise ValidationError("La fila ya no se puede editar.")
    if row.updated_at.isoformat() != version:
        raise ValidationError("La fila cambió durante la edición. Vuelve a abrirla para revisar la versión actual.")

    try:
        original = form_data(row)
    except ValidationError:
        original = None
    if original == data:
        return False

    serialized = {key: value.isoformat() if isinstance(value, date) else value for key, value in data.items()}
    values = workbook_values(row.sheet_name, serialized)
    for key, value in values.items():
        setattr(row, key, value)
    row.status = ImportStatus.PENDING
    row.validation_notes = ""
    try:
        validate_row(row)
    except ValidationError as error:
        row.validation_notes = review_error(error)
    row._history_user = actor
    row.save(update_fields=[*values, "status", "validation_notes", "updated_at"])
    return True


@transaction.atomic
def stage_workbook(upload, actor):
    batch = uuid4()
    rows = [staging_row(batch, *row) for row in read_workbook(upload)]
    bulk_create_with_history(rows, StagingAsset, batch_size=200, default_user=actor)
    invalid = 0
    for row in rows:
        try:
            validate_row(row)
        except ValidationError as error:
            update_review(row, actor=actor, notes=review_error(error))
            invalid += 1
    return batch, len(rows), invalid


@transaction.atomic
def set_import_status(queryset, status, actor):
    changed, invalid = 0, 0
    for row in queryset.exclude(status=ImportStatus.IMPORTED).order_by("pk").select_for_update().iterator():
        if status == ImportStatus.APPROVED and row.batch_id:
            try:
                validate_row(row)
            except ValidationError as error:
                update_review(row, actor=actor, status=ImportStatus.PENDING, notes=review_error(error))
                invalid += 1
                continue
        if row.status != status:
            changed += 1
        update_review(row, actor=actor, status=status)
    return changed, invalid


def save_new(record, actor):
    record._history_user = actor
    record.save()


def publish_asset(asset, employee, data, actor):
    save_new(asset, actor)
    for model, fields in (
        (AssetSpecs, ("ram", "storage", "processor", "operating_system")),
        (AssetNetwork, ("hostname", "mac_address", "imei", "phone_number", "operator")),
    ):
        values = {key: data[key] or None for key in fields}
        if any(values.values()):
            save_new(model(asset=asset, **values), actor)
    if data["supplier"] or data["warranty_start"] or data["warranty_observations"]:
        save_new(AssetWarranty(
            asset=asset, supplier=data["supplier"] or None, purchase_date=data["purchase_date"],
            warranty_start=data["warranty_start"], warranty_end=data["warranty_end_date"],
            observations=data["warranty_observations"] or None,
        ), actor)
    if employee:
        create_assignment(
            asset_id=asset.pk, employee_id=employee.pk, assigned_by=actor,
            initial_condition=data["initial_condition"], observations=data["assignment_observations"] or None,
            due_on=data["due_on"],
        )


@transaction.atomic
def publish_row(pk, actor):
    row = StagingAsset.objects.select_for_update().filter(
        pk=pk, batch_id__isnull=False, status=ImportStatus.APPROVED,
    ).first()
    if row is None:
        return None
    try:
        with transaction.atomic():
            data = form_data(row)
            if row.sheet_name == EMPLOYEES:
                employee = employee_for_row(row, data)
                if employee._state.adding:
                    save_new(employee, actor)
            else:
                asset, employee = asset_for_row(row, data, publishing=True)
                publish_asset(asset, employee, data, actor)
            update_review(row, actor=actor, status=ImportStatus.IMPORTED)
    except (ValidationError, IntegrityError) as error:
        row.refresh_from_db()
        notes = review_error(error) if isinstance(error, ValidationError) else (
            "La publicación encontró un conflicto de datos. Comprueba si el identificador ya existe y vuelve a intentar."
        )
        update_review(row, actor=actor, notes=notes)
        return False
    return True


def publish_rows(queryset, actor):
    ids = list(queryset.filter(batch_id__isnull=False, status=ImportStatus.APPROVED)
               .order_by("-sheet_name", "batch_id", "row_number", "pk").values_list("pk", flat=True))
    results = [publish_row(pk, actor) for pk in ids]
    return results.count(True), results.count(False)
