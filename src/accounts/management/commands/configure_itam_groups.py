from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, User


SUPPORT_GROUP = "Técnicos de Soporte"
AUDITOR_GROUP = "Auditores"

EVIDENCE_MODELS = (
    "assignments.assignment",
    "assignments.offboardingrecord",
    "assignments.offboardingrecorditem",
    "inventory.asset",
    "inventory.assetspecs",
    "inventory.decommissionedasset",
    "maintenance.maintenancedocument",
    "maintenance.maintenancerecord",
)
CATALOG_MODELS = (
    "inventory.brand",
    "inventory.category",
    "inventory.modelasset",
    "organizations.area",
    "organizations.company",
    "organizations.site",
)
SUPPORT_EDITABLE_MODELS = (
    "assignments.assignment",
    "employees.employee",
    "inventory.asset",
    "inventory.assetnetwork",
    "inventory.assetspecs",
    "inventory.assetwarranty",
    "maintenance.maintenancedocument",
    "maintenance.maintenancerecord",
)

GROUP_POLICY = {
    SUPPORT_GROUP: {
        "view": EVIDENCE_MODELS + CATALOG_MODELS + (
            "assignments.employeeassetsummary",
            "employees.retiredemployee",
            *SUPPORT_EDITABLE_MODELS,
        ),
        "add": SUPPORT_EDITABLE_MODELS,
        "change": SUPPORT_EDITABLE_MODELS,
    },
    AUDITOR_GROUP: {"view": EVIDENCE_MODELS + CATALOG_MODELS},
}


class Command(BaseCommand):
    help = "Muestra o aplica los permisos de los grupos de Soporte TI y Auditores."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Guarda los permisos de los grupos.")
        parser.add_argument("--actor", help="Usuario administrador que autoriza el cambio.")

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options["apply"]
        actor = None
        if apply:
            actor = User.objects.filter(
                username=options["actor"], role=Role.ADMINISTRATOR,
                is_active=True, is_staff=True, is_superuser=True,
            ).first()
            if actor is None:
                raise CommandError("Indica un administrador activo con --actor para registrar el cambio.")

        available = {
            f"{permission.content_type.app_label}.{permission.codename}": permission
            for permission in Permission.objects.select_related("content_type")
        }
        groups = Group.objects.select_for_update() if apply else Group.objects.all()
        for name, actions in GROUP_POLICY.items():
            desired = set()
            for action, models in actions.items():
                for model in models:
                    app_label, model_name = model.split(".")
                    desired.add(f"{app_label}.{action}_{model_name}")
            missing = desired - available.keys()
            if missing:
                raise CommandError(f"Faltan permisos de Django para {name}: {', '.join(sorted(missing))}")

            group = groups.filter(name=name).first()
            current = set()
            if group is not None:
                current = {
                    f"{permission.content_type.app_label}.{permission.codename}"
                    for permission in group.permissions.select_related("content_type")
                }
            self.stdout.write(f"{name} (+{len(desired - current)}, -{len(current - desired)})")
            for permission in sorted(desired - current):
                self.stdout.write(f"  + {permission}")
            for permission in sorted(current - desired):
                self.stdout.write(f"  - {permission}")

            if apply and desired != current:
                if group is None:
                    group = Group(name=name)
                group._history_user = actor
                if group.pk is None:
                    group.save()
                group.permissions.set(available[permission] for permission in desired)

        if not apply:
            self.stdout.write("Vista previa. Usa --apply y --actor para guardar.")
