from django import forms
from django.core.exceptions import ValidationError

from employees.models import DocumentType, EmployeeStatus
from inventory.models import AssetStatus, PropertyType


class TextIdentifier(forms.CharField):
    def to_python(self, value):
        if value is not None and not isinstance(value, str):
            raise ValidationError("Usa formato Texto en Excel para conservar el identificador completo.")
        return super().to_python(value)


class ImportDate(forms.DateField):
    def __init__(self, **kwargs):
        super().__init__(required=False, input_formats=["%Y-%m-%d"], **kwargs)


class EmployeeRow(forms.Form):
    document_number = TextIdentifier(label="Documento", max_length=50)
    document_type = forms.ChoiceField(label="Tipo de documento", choices=DocumentType.choices)
    full_name = forms.CharField(label="Nombre completo", max_length=255)
    company = forms.CharField(label="Código compañía empleado", max_length=20)
    site = forms.CharField(label="Sede empleado", max_length=200, required=False)
    area = forms.CharField(label="Área empleado", max_length=200, required=False)
    email = forms.EmailField(label="Correo", required=False)
    phone = TextIdentifier(label="Teléfono", max_length=50, required=False)
    status = forms.ChoiceField(label="Estado empleado", choices=EmployeeStatus.choices, required=False)


STOCK_STATUSES = (AssetStatus.AVAILABLE, AssetStatus.RETIRED, AssetStatus.LOST, AssetStatus.IN_TRANSIT)


class AssetRow(forms.Form):
    legacy_asset_tag = TextIdentifier(label="Placa", max_length=50, required=False)
    serial_number = TextIdentifier(label="Serie", max_length=100, required=False)
    import_reference = TextIdentifier(label="Referencia de carga", max_length=100, required=False)
    category = forms.CharField(label="Tipo de activo", max_length=100)
    brand = forms.CharField(label="Marca", max_length=100, required=False)
    model = forms.CharField(label="Modelo", max_length=150, required=False)
    company = forms.CharField(label="Código compañía administradora", max_length=20)
    owner_company = forms.ChoiceField(label="Código compañía propietaria", choices=[("ACE", "ACE"), ("SOL", "SOL")])
    property_type = forms.ChoiceField(label="Tipo de propiedad", choices=PropertyType.choices)
    site = forms.CharField(label="Ubicación física", max_length=200, required=False)
    status = forms.ChoiceField(label="Estado sin custodio", choices=[(s.value, s.label) for s in STOCK_STATUSES], required=False)
    purchase_date = ImportDate(label="Fecha de compra")
    warranty_end_date = ImportDate(label="Fin de garantía")
    observations = forms.CharField(label="Observaciones del activo", required=False)
    ram = forms.CharField(label="Memoria RAM", max_length=50, required=False)
    storage = forms.CharField(label="Almacenamiento", max_length=50, required=False)
    processor = forms.CharField(label="Procesador", max_length=100, required=False)
    operating_system = forms.CharField(label="Sistema operativo", max_length=100, required=False)
    hostname = forms.CharField(label="Hostname", max_length=100, required=False)
    mac_address = TextIdentifier(label="Dirección MAC", max_length=50, required=False)
    imei = TextIdentifier(label="IMEI", max_length=50, required=False)
    phone_number = TextIdentifier(label="Número de línea", max_length=50, required=False)
    operator = forms.CharField(label="Operador", max_length=50, required=False)
    supplier = forms.CharField(label="Proveedor de garantía", max_length=150, required=False)
    warranty_start = ImportDate(label="Inicio de garantía")
    warranty_observations = forms.CharField(label="Observaciones de garantía", required=False)
    employee_document = TextIdentifier(label="Documento del custodio", max_length=50, required=False)
    initial_condition = forms.CharField(label="Condición de entrega", required=False)
    assignment_observations = forms.CharField(label="Observaciones de custodia", required=False)
    due_on = ImportDate(label="Devolución prevista")

    def clean(self):
        data = super().clean()
        if not any(data.get(key) for key in ("legacy_asset_tag", "serial_number", "import_reference")):
            self.add_error("import_reference", "Completa la placa, la serie o una referencia estable de carga.")
        if data.get("employee_document"):
            if not data.get("initial_condition"):
                self.add_error("initial_condition", "Registra la condición real del activo para publicar la custodia.")
            if data.get("status"):
                self.add_error("status", "Deja este campo vacío cuando el activo tiene custodio.")
        elif any(data.get(key) for key in ("initial_condition", "assignment_observations", "due_on")):
            self.add_error("employee_document", "Identifica al custodio para registrar los datos de entrega.")
        if data.get("warranty_start") and data.get("warranty_end_date"):
            if data["warranty_start"] > data["warranty_end_date"]:
                self.add_error("warranty_end_date", "El fin de garantía debe ser posterior o igual a su inicio.")
        return data


class WorkbookUpload(forms.Form):
    workbook = forms.FileField(label="Archivo Excel", widget=forms.FileInput(attrs={"accept": ".xlsx"}))
