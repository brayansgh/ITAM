from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assignments", "0006_devolucion_activos")]

    operations = [
        migrations.AddField(
            model_name=model,
            name="delivery_id",
            field=models.UUIDField(db_index=True, editable=False, null=True),
        )
        for model in ("assignment", "historicalassignment")
    ]
