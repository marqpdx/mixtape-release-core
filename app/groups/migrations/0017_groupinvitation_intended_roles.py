import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0016_groupcontext"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupinvitation",
            name="intended_roles",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=50),
                blank=True,
                default=list,
                size=None,
            ),
        ),
    ]
