from django import forms
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.hashers import is_password_usable
from django.urls import reverse
from django.utils.html import format_html


class PasswordStatusWidget(forms.Widget):
    read_only = True
    template_name = "admin/accounts/password_status.html"

    def get_context(self, name, value, attrs):
        # El hash nunca se entrega al contexto de la plantilla.
        context = super().get_context(name, None, attrs)
        context["widget"]["status"] = (
            "Contraseña configurada" if value and is_password_usable(value)
            else "Sin contraseña habilitada"
        )
        return context


class AccountUserChangeForm(UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "password" in self.fields:
            password = self.fields["password"]
            password.widget = PasswordStatusWidget()
            if self.instance.pk:
                password.help_text = format_html(
                    '<a href="{}">Cambiar contraseña</a>',
                    reverse("admin:auth_user_password_change", args=[self.instance.pk]),
                )
        descriptions = {
            "role": "Controla los flujos de ITAM. No asigna automáticamente permisos de Django.",
            "is_staff": "Permite entrar al administrador. Los grupos y permisos determinan qué módulos puede usar.",
            "groups": "Asigna grupos para administrar permisos compartidos. El usuario hereda sus permisos.",
            "user_permissions": "Permisos adicionales para este usuario. Úsalos solo cuando los grupos no sean suficientes.",
        }
        for name, description in descriptions.items():
            if name in self.fields:
                self.fields[name].help_text = description
