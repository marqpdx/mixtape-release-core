import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atrium", "0002_atriumsession_dial_mode"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="atriumsession",
            name="sponsor_content_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="atriumsession",
            name="sponsor_object_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
