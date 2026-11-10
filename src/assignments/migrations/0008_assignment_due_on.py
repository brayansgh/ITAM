from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assignments", "0007_assignment_delivery_id")]

    operations = [
        migrations.AddField(
            model_name=model,
            name="due_on",
            field=models.DateField(blank=True, editable=False, null=True, verbose_name="Devolución prevista"),
        )
        for model in ("assignment", "historicalassignment")
    ]
