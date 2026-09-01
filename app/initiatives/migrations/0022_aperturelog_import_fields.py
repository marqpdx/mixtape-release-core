from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0021_aperturelog_compact_cadence"),
    ]

    operations = [
        migrations.AddField(
            model_name="aperturelog",
            name="import_source",
            field=models.JSONField(
                blank=True,
                default=None,
                null=True,
                help_text=(
                    "Set when this log was populated by import_conversation. "
                    "Schema: {platform, conversation_id, title, model, exported, imported_at}"
                ),
            ),
        ),
        migrations.AddField(
            model_name="aperturelogentry",
            name="source_turn_index",
            field=models.IntegerField(
                blank=True,
                default=None,
                null=True,
                help_text="0-based position in the original imported conversation. Null for native entries.",
            ),
        ),
        migrations.AddField(
            model_name="aperturelogentry",
            name="source_timestamp",
            field=models.DateTimeField(
                blank=True,
                default=None,
                null=True,
                help_text="Original timestamp of an imported conversation turn. Null for native entries.",
            ),
        ),
    ]
