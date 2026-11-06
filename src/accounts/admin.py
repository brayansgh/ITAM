from .forms import AccountUserChangeForm


class PermissionChangeAuditMixin:
    """Guarda el antes y después de relaciones que simple-history no rastrea."""

    permission_audit_fields = ()

    def construct_change_message(self, request, form, formsets, add=False):
        message = super().construct_change_message(request, form, formsets, add)
        for name, label in self.permission_audit_fields:
            if name not in form.changed_data:
                continue
            field = form.fields[name]
            initial = form.initial.get(name) or []
            initial_ids = [getattr(item, "pk", item) for item in initial]
            before = field.queryset.filter(pk__in=initial_ids)
            after = form.cleaned_data.get(name) or []
            old_names = ", ".join(sorted(str(item) for item in before)) or "Sin asignar"
            new_names = ", ".join(sorted(str(item) for item in after)) or "Sin asignar"
            message.append({"changed": {"fields": [f"{label}: {old_names} → {new_names}"]}})
        return message


class AccountUserAdminMixin(PermissionChangeAuditMixin):
    form = AccountUserChangeForm
    permission_audit_fields = (("groups", "Grupos"), ("user_permissions", "Permisos individuales"))
    list_display = ("username", "first_name", "last_name", "email", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "groups")
    fieldsets = (
        ("Cuenta", {"fields": ("username", "password")}),
        ("Información personal", {"fields": ("first_name", "last_name", "email")}),
        ("Acceso a ITAM", {"fields": ("role", "is_active", "is_staff")}),
        ("Permisos por grupo", {"fields": ("groups",), "description": "Utiliza grupos para asignar conjuntos de permisos."}),
        ("Permisos individuales y acceso total", {"fields": ("user_permissions", "is_superuser"), "classes": ("collapse",)}),
        ("Fechas de la cuenta", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
    )
    add_fieldsets = (
        ("Cuenta", {"classes": ("wide",), "fields": ("username", "password1", "password2")}),
        ("Acceso a ITAM", {"fields": ("role", "is_active", "is_staff", "groups")}),
    )



class AccountGroupAdminMixin(PermissionChangeAuditMixin):
    permission_audit_fields = (("permissions", "Permisos del grupo"),)
