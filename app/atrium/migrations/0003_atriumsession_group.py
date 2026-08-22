import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atrium", "0002_atriumsession_dial_mode"),
        ("groups", "0019_group_dispatch_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="atriumsession",
            name="group",
            field=models.ForeignKey(
                blank=True,
                help_text="If set, this session is scoped to the group's Atrium surface.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="atrium_sessions",
                to="groups.group",
            ),
        ),
    ]
