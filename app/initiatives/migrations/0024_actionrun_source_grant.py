# Generated manually for Sourcework audit linkage.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sourcework", "0001_initial"),
        ("initiatives", "0023_aperturelog_source_timestamp"),
    ]

    operations = [
        migrations.AddField(
            model_name="actionrun",
            name="source_grant",
            field=models.ForeignKey(
                blank=True,
                help_text="External Source Grant used by this action, when applicable.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="action_runs",
                to="sourcework.sourcegrant",
            ),
        ),
    ]
