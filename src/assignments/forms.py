from django import forms
from django.forms import formset_factory

from .models import ReturnReason


class OffboardingForm(forms.Form):
    observations = forms.CharField(
        required=False,
        label="Observaciones generales",
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "Escribe aquí las observaciones generales del acta..."
        })
    )


class OffboardingItemForm(forms.Form):
    assignment_id = forms.UUIDField(
        widget=forms.HiddenInput()
    )

    selected = forms.BooleanField(
        required=False,
        label="Recibir este activo"
    )

    condition = forms.CharField(
        required=False,
        label="Condición del activo",
        widget=forms.Textarea(attrs={
            "rows": 2,
            "placeholder": "Describe el estado físico del activo..."
        })
    )

    observations = forms.CharField(
        required=False,
        label="Observaciones del activo",
        widget=forms.Textarea(attrs={
            "rows": 2,
            "placeholder": "Observaciones adicionales..."
        })
    )

    def clean(self):
        cleaned_data = super().clean()

        selected = cleaned_data.get("selected")
        condition = cleaned_data.get("condition")

        if selected and not condition:
            self.add_error(
                "condition",
                "Debes indicar la condición del activo que estás recibiendo."
            )

        return cleaned_data


OffboardingItemFormSet = formset_factory(
    OffboardingItemForm,
    extra=0
)



class ActiveReturnForm(forms.Form):
    assignments = forms.ModelMultipleChoiceField(queryset=None, label="Activos que se reciben", widget=forms.CheckboxSelectMultiple)
    reason = forms.ChoiceField(label="Motivo de devolución", choices=[("", "Selecciona un motivo"), *ReturnReason.choices])
    condition = forms.CharField(label="Condición al recibir", widget=forms.Textarea(attrs={"rows": 3}))
    observations = forms.CharField(label="Observaciones", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    request_decommission = forms.BooleanField(label="Tramitar la baja de los activos seleccionados", required=False)

    def __init__(self, *args, assignments, can_request_decommission, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignments"].queryset = assignments
        self.fields["assignments"].label_from_instance = self.asset_label
        if not can_request_decommission:
            del self.fields["request_decommission"]

    @staticmethod
    def asset_label(assignment):
        asset = assignment.asset
        parts = [str(asset), asset.category.name]
        parts.extend(str(value) for value in (asset.brand, asset.model) if value)
        network = getattr(asset, "network", None)
        if network and network.hostname:
            parts.append(f"Equipo {network.hostname}")
        if asset.serial_number:
            parts.append(f"Serie {asset.serial_number}")
        if assignment.due_on:
            parts.append(f"Préstamo hasta el {assignment.due_on:%d/%m/%Y}")
        return " · ".join(parts)
