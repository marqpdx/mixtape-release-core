from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("folio", "0006_interpretation_decisions")]
    operations = [migrations.AddField(model_name="folio", name="local_only",
                                    field=models.BooleanField(default=False))]
