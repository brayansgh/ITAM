import os

path = "src/employees/admin.py"
if not os.path.exists(path):
    for root, dirs, files in os.walk('src'):
        if 'employees' in root and 'admin.py' in files:
            path = os.path.join(root, 'admin.py')
            break

with open(path, "a") as f:
    f.write("""
# --- INTERCEPTOR DE FORMULARIO (ESTADO: RETIRO) ---
from django.contrib import admin
from django.apps import apps
from django.http import HttpResponse

EmployeeModel = apps.get_model('employees', 'Employee')
if admin.site.is_registered(EmployeeModel):
    OriginalAdmin = admin.site._registry[EmployeeModel].__class__
    admin.site.unregister(EmployeeModel)
    
    class OffboardingEmployeeAdmin(OriginalAdmin):
        def get_form(self, request, obj=None, **kwargs):
            form = super().get_form(request, obj, **kwargs)
            # Buscar el campo de estado e inyectar la opción de retiro
            for field_name in ['status', 'estado']:
                if field_name in form.base_fields:
                    field = form.base_fields[field_name]
                    if hasattr(field, 'choices'):
                        choices = list(field.choices)
                        if not any(c[0] == 'RETIRO' for c in choices):
                            choices.append(('RETIRO', 'Retiro de la compañía'))
                            field.choices = choices
            return form

        def response_change(self, request, obj):
            status_val = str(getattr(obj, 'status', getattr(obj, 'estado', ''))).upper()
            
            # Si el usuario seleccionó Retiro en el formulario
            if status_val == 'RETIRO':
                try:
                    from inventory.offboarding_pdf import generate_and_save_offboarding_pdf
                    Asset = apps.get_model('inventory', 'Asset')
                    assets_liberados = []
                    
                    # Liberación masiva de hardware asignado
                    for asset in Asset.objects.exclude(status__icontains="DECOMMISSION"):
                        if getattr(asset, 'employee', None) == obj or getattr(asset, 'assigned_to', None) == obj:
                            setattr(asset, 'employee', None)
                            setattr(asset, 'assigned_to', None)
                            if hasattr(asset, 'status'): asset.status = 'AVAILABLE'
                            asset.save()
                            assets_liberados.append(asset)
                            
                    # Retornar el PDF inline saltándose la redirección habitual
                    return generate_and_save_offboarding_pdf(obj, assets_liberados, request.user)
                except Exception as e:
                    self.message_user(request, f"Error al generar acta: {e}", level='ERROR')
                    
            return super().response_change(request, obj)

    admin.site.register(EmployeeModel, OffboardingEmployeeAdmin)
""")
