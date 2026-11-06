from django import forms
from .models import Asset, AssetGroup, Category


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
        if 'owner_company' in self.fields:
            self.fields['owner_company'].required = True
            self.fields['owner_company'].queryset = self.fields['owner_company'].queryset.filter(code__in=('ACE', 'SOL'))
        if 'status' in self.fields:
            forbidden = {'DECOMMISSIONED'}
            if not existing:
                forbidden.add('ASSIGNED')
            self.fields['status'].choices = [(key, label) for key, label in self.fields['status'].choices if key not in forbidden]

    def clean(self):
        data = super().clean()
        category = data.get('category')
        group = data.get('group')
        if category and group and category.group != group:
            self.add_error('category', 'El tipo de activo no pertenece al grupo elegido.')
        if category and not category.group and self.instance._state.adding:
            self.add_error('category', 'Selecciona un tipo de activo clasificado por grupo.')
        model = data.get('model')
        if category and model and model.category_id and model.category_id != category.pk:
            previous = Asset.objects.filter(pk=self.instance.pk).values('category_id', 'model_id').first()
            if not previous or previous['category_id'] != category.pk or previous['model_id'] != model.pk:
                self.add_error('model', 'El modelo debe corresponder al tipo de activo seleccionado.')
        return data
