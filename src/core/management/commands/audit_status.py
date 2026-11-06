import json

from django.apps import apps
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.utils import timezone


DOMAIN_APPS = {"accounts", "assignments", "data_imports", "employees", "inventory", "maintenance", "organizations"}


class Command(BaseCommand):
    help = "Comprueba cobertura y conteos de auditoría sin exponer datos personales. Solo lectura."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--fail-on-missing", action="store_true")

    def handle(self, *args, **options):
        models = [model for model in apps.get_models()
                  if model._meta.app_label in DOMAIN_APPS and not model._meta.proxy
                  and not model.__name__.startswith("Historical")]
        models.append(Group)
        report = {"timezone": timezone.get_current_timezone_name(), "models": [], "missing_models": []}
        for model in sorted(models, key=lambda item: item._meta.label):
            if not hasattr(model, "history"):
                report["missing_models"].append(model._meta.label)
                continue
            history = model.history.all()
            counts = history.aggregate(
                versions=Count("history_id"), creations=Count("history_id", filter=Q(history_type="+")),
                modifications=Count("history_id", filter=Q(history_type="~")),
                deletions=Count("history_id", filter=Q(history_type="-")),
                versions_without_actor=Count("history_id", filter=Q(history_user__isnull=True)),
            )
            counts.update({
                "model": model._meta.label,
                "current_records": model._default_manager.count(),
                "current_records_with_versions": model._default_manager.filter(
                    pk__in=history.values(model._meta.pk.attname),
                ).count(),
            })
            report["models"].append(counts)
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        else:
            self.stdout.write("Conteos por modelo; versiones y operaciones de negocio no son equivalentes.")
            for row in report["models"]:
                self.stdout.write(
                    f"{row['model']}: {row['versions']} versiones; "
                    f"registros actuales con versiones: {row['current_records_with_versions']}/{row['current_records']}; "
                    f"versiones sin responsable: {row['versions_without_actor']}"
                )
            self.stdout.write("Modelos sin seguimiento: " + (", ".join(report["missing_models"]) or "ninguno"))
        if options["fail_on_missing"] and report["missing_models"]:
            raise CommandError("Hay modelos del dominio sin seguimiento de auditoría.")
