from django import forms
from django.core.exceptions import ValidationError
from django.forms import formset_factory


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
