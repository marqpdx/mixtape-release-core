# Generated manually for Group emblem FK

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0001_initial"),
        ("groups", "0003_groupinvitation_group_invites"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="emblem",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="groups",
                to="identity.emblemavatar",
            ),
        ),
    ]

