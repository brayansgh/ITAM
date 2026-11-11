from datetime import date, datetime, time
from io import BytesIO
from math import isfinite
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation

from inventory.models import Brand, Category, ModelAsset
from organizations.models import Area, Company, Site

from .forms import AssetRow, EmployeeRow, TextIdentifier


EMPLOYEES = "Empleados"
ASSETS = "Activos"
ROW_FORMS = {EMPLOYEES: EmployeeRow, ASSETS: AssetRow}
MAX_ROWS = 2000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024


def catalog_reference(record):
    return f"{record.name} [{record.pk}]"


def add_headers(sheet, headers):
    sheet.append(headers)
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="003366")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.column_dimensions[cell.column_letter].width = max(20, min(len(cell.value) + 5, 38))
    sheet.row_dimensions[1].height = 32


def add_catalog(book, title, headers, rows):
    sheet = book.create_sheet(title)
    add_headers(sheet, headers)
    for row in rows:
        sheet.append(row)
        # Los catálogos pueden contener nombres que empiezan por signos de fórmula.
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    sheet.column_dimensions["A"].width = 66
    sheet.auto_filter.ref = sheet.dimensions


def build_workbook():
    book = Workbook()
    instructions = book.active
    instructions.title = "Instrucciones"
    add_headers(instructions, ["Importación inicial de ITAM"])
    instructions.column_dimensions["A"].width = 112
    notes = [
        "Registra una persona por fila en Empleados y un equipo por fila en Activos. Conserva los encabezados.",
        f"Usa un archivo .xlsx con un máximo de {MAX_ROWS} registros y 8 MiB. Las hojas de catálogos son de consulta.",
        "Los encabezados en naranja indican campos obligatorios. Pega valores sin fórmulas y conserva el formato Texto en identificadores.",
        "En Empleados, usa el documento completo. El estado predeterminado es ACTIVE. Elige la sede del catálogo de ubicaciones compartidas y un área de la compañía del empleado.",
        "En Activos, completa al menos placa, serie o referencia de carga. Conserva la misma referencia si vuelves a enviar el mismo equipo.",
        "Indica por separado quién administra el activo, quién es su propietario y si es propio, arrendado o de terceros. El código interno se genera al publicar.",
        "Copia los valores de los catálogos. Si un valor falta, créalo por el flujo habitual y descarga el catálogo actualizado. La ubicación del activo puede ser compartida.",
        "Para una custodia vigente, usa el documento del empleado y la condición real de entrega. Deja vacío Estado sin custodio. Publica primero la persona o selecciónala en la misma publicación masiva.",
        "Sin custodio, el estado predeterminado es AVAILABLE. Registra mantenimientos y bajas definitivas por sus flujos habituales.",
        "Usa fechas de Excel o AAAA-MM-DD. La fecha de registro de la custodia será la de publicación. La carga no genera ni adjunta actas.",
        "Al subir el libro, las filas quedan pendientes en Importaciones. Revisa y aprueba las válidas antes de pasarlas a producción.",
    ]
    for index, note in enumerate(notes, 2):
        cell = instructions.cell(index, 1, note)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        instructions.row_dimensions[index].height = 34

    for title, form in ROW_FORMS.items():
        sheet = book.create_sheet(title)
        add_headers(sheet, [field.label for field in form.base_fields.values()])
        for index, field in enumerate(form.base_fields.values(), 1):
            column = get_column_letter(index)
            if field.required:
                sheet.cell(1, index).fill = PatternFill("solid", fgColor="A64413")
            if isinstance(field, TextIdentifier):
                sheet.column_dimensions[column].number_format = "@"
            if getattr(field, "choices", None):
                options = ",".join(value for value, _ in field.choices)
                dropdown = DataValidation(type="list", formula1=f'"{options}"', allow_blank=not field.required,
                                          showErrorMessage=True, errorTitle="Valor inválido",
                                          error="Selecciona uno de los valores de la lista.")
                sheet.add_data_validation(dropdown)
                dropdown.add(f"{column}2:{column}{MAX_ROWS + 1}")

    add_catalog(book, "Compañías", ["Código", "Compañía"],
                Company.objects.order_by("code").values_list("code", "name"))
    add_catalog(book, "Tipos y marcas", ["Tipo de activo", "Grupo"],
                ((record.name, record.get_group_display())
                 for record in Category.objects.exclude(group="").order_by("name")))
    add_catalog(book, "Marcas", ["Marca"], Brand.objects.order_by("name").values_list("name"))
    add_catalog(book, "Modelos", ["Valor para Excel", "Marca"],
                ((catalog_reference(record), record.brand.name if record.brand_id else "")
                 for record in ModelAsset.objects.select_related("brand").order_by("name", "pk")))
    add_catalog(book, "Ubicaciones", ["Valor para Excel", "Ciudad"],
                ((catalog_reference(record), record.city) for record in Site.objects.order_by("name", "pk")))
    add_catalog(book, "Áreas", ["Área", "Compañía"],
                Area.objects.order_by("company__code", "name").values_list("name", "company__code"))
    add_catalog(book, "Opciones", ["Hoja", "Columna", "Valor para Excel", "Significado"],
                ((title, field.label, value, str(label)) for title, form in ROW_FORMS.items()
                 for field in form.base_fields.values() for value, label in getattr(field, "choices", [])))
    output = BytesIO()
    book.save(output)
    output.seek(0)
    return output


def cell_value(value):
    if isinstance(value, datetime) and value.time() == time():
        return value.date().isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float) and not isfinite(value):
        raise ValidationError("El Excel contiene un número fuera de rango.")
    return value.strip() if isinstance(value, str) else value


def read_workbook(upload):
    if not upload.name.lower().endswith(".xlsx") or upload.size > MAX_FILE_BYTES:
        raise ValidationError("Sube un archivo .xlsx de hasta 8 MiB.")

    try:
        with ZipFile(upload) as archive:
            entries = archive.infolist()
            if len(entries) > 200 or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
                raise ValidationError("El contenido interno del archivo Excel excede el límite permitido.")
        book = load_workbook(upload, read_only=True, keep_links=False)
        try:
            rows = []
            for name, form in ROW_FORMS.items():
                if name not in book.sheetnames:
                    raise ValidationError(f"Falta la hoja «{name}» de la plantilla.")
                keys = list(form.base_fields)
                expected = [field.label for field in form.base_fields.values()] + [None]
                sheet = book[name]
                if not hasattr(sheet, "reset_dimensions"):
                    raise ValidationError(f"«{name}» debe ser una hoja de datos.")
                sheet.reset_dimensions()
                source = sheet.iter_rows(max_col=len(expected))
                header = next(source, ())
                if [cell_value(cell.value) for cell in header] != expected:
                    raise ValidationError(f"Los encabezados de «{name}» no coinciden con la plantilla.")
                for number, cells in enumerate(source, 2):
                    if number > MAX_ROWS + 1:
                        raise ValidationError(f"«{name}» supera el límite de {MAX_ROWS} filas de datos.")
                    values = [cell_value(cell.value) for cell in cells]
                    if not any(value is not None and value != "" for value in values):
                        continue
                    if values[-1] is not None or any(cell.data_type in ("f", "e") for cell in cells):
                        raise ValidationError(f"«{name}», fila {number}: usa valores válidos y solo las columnas de la plantilla.")
                    rows.append((name, number, dict(zip(keys, values))))
                    if len(rows) > MAX_ROWS:
                        raise ValidationError(f"El libro excede el máximo de {MAX_ROWS} registros.")
        finally:
            book.close()
    except (BadZipFile, InvalidFileException, KeyError, ValueError, OSError,
            ParseError, TypeError, IndexError, EOFError, RuntimeError) as error:
        raise ValidationError("No se pudo leer el Excel. Guarda una copia nueva de la plantilla en formato .xlsx.") from error

    if not rows:
        raise ValidationError("Completa al menos una fila en Empleados o Activos.")
    return rows
