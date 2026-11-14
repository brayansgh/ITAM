from uuid import UUID

from django import forms
from django.db.models import Value
from django.db.models.functions import Lower, Trim
from employees.models import Employee, EmployeeStatus

from .models import Asset, AssetGroup, AssetStatus, Category, ModelAsset


class ModelAssetForm(forms.ModelForm):
    class Meta:
        model = ModelAsset
        fields = ('name', 'brand')

    def clean(self):
        data = super().clean()
        if 'name' not in data or 'brand' not in data:
            return data
        if not self.instance._state.adding and not {'name', 'brand'}.intersection(self.changed_data):
            return data

        duplicates = ModelAsset.objects.filter(brand=data['brand']).alias(
            normalized_name=Lower(Trim('name')),
        ).filter(normalized_name=Lower(Value(data['name'])))
        if duplicates.exclude(pk=self.instance.pk).exists():
            self.add_error('name', 'Este modelo ya está registrado para la marca seleccionada.'
                           if data['brand'] else 'Este modelo ya está registrado sin marca.')
        return data


class AssetRegistrationForm(forms.ModelForm):
    group = forms.ChoiceField(label='Grupo', choices=[('', 'Selecciona un grupo'), *AssetGroup.choices])

    class Meta:
        model = Asset
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing = not self.instance._state.adding
        current_group = self.instance.category.group if self.instance.category_id else ''
        self.fields['group'].initial = current_group
        self.fields['group'].required = not existing or bool(current_group)
        selected = self.data.get('group') if self.is_bound else current_group
        if 'category' in self.fields:
            categories = Category.objects.all().order_by('name')
            if selected:
                categories = categories.filter(group=selected)
            elif not existing:
                categories = categories.none()
            self.fields['category'].queryset = categories
        if not existing and 'brand' in self.fields and 'model' in self.fields:
            models = self.fields['model'].queryset
            brand = self.data.get(self.add_prefix('brand')) if self.is_bound else self.initial.get('brand')
            try:
                brand_id = UUID(str(brand))
            except ValueError:
                models = models.none()
            else:
                models = models.filter(brand_id=brand_id).order_by('name', 'pk')
            self.fields['model'].queryset = models
            self.fields['model'].help_text = 'Selecciona una marca para ver sus modelos.'
        if 'owner_company' in self.fields:
            self.fields['owner_company'].required = True
            self.fields['owner_company'].queryset = self.fields['owner_company'].queryset.filter(code__in=('ACE', 'SOL'))
        if 'status' in self.fields:
            forbidden = {'DECOMMISSIONED'}
            supports_assignment = 'assignment_employee' in self.fields
            if (not existing or self.instance.status == AssetStatus.AVAILABLE) and not supports_assignment:
                forbidden.add('ASSIGNED')
            self.fields['status'].choices = [
                (key, 'Asignar a una persona' if supports_assignment and key == AssetStatus.ASSIGNED else label)
                for key, label in self.fields['status'].choices if key not in forbidden
            ]

    def clean(self):
        data = super().clean()
        category = data.get('category')
        group = data.get('group')
        if category and group and category.group != group:
            self.add_error('category', 'El tipo de activo no pertenece al grupo elegido.')
        if category and not category.group and self.instance._state.adding:
            self.add_error('category', 'Selecciona un tipo de activo clasificado por grupo.')
        return data


class AssetWithAssignmentForm(AssetRegistrationForm):
    assignment_employee = forms.ModelChoiceField(
        queryset=Employee.objects.exclude(status=EmployeeStatus.RETIRO).order_by('full_name'),
        label='Empleado responsable',
        required=False,
    )
    assignment_condition = forms.CharField(
        label='Condición de entrega', widget=forms.Textarea(attrs={'rows': 3}), required=False,
    )
    assignment_observations = forms.CharField(
        label='Observaciones / Pérdida / Daños',
        help_text='Este texto aparecerá en el acta de entrega.',
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
    )

    def clean(self):
        data = super().clean()
        self.assign_on_save = data.get('status') == AssetStatus.ASSIGNED
        if self.assign_on_save:
            # El servicio registra la custodia antes de pasar el activo a ASSIGNED.
            data['status'] = AssetStatus.AVAILABLE
            for name in ('assignment_employee', 'assignment_condition'):
                if not data.get(name) and name not in self.errors:
                    self.add_error(name, 'Este campo es obligatorio al asignar el activo.')
        return data
