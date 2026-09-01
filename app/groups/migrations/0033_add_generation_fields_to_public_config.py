from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0032_add_group_public_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouppublicconfig",
            name="rows",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text=(
                    "T2: AI-assembled Rows layout. Ordered list of Row objects: "
                    "[{type: str, content: {...}}]. Null for T1. "
                    "Frontend renders from rows when present; T1 synthesized payload has rows=null."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="generation_status",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("pending", "Pending"),
                    ("complete", "Complete"),
                    ("stale", "Stale"),
                ],
                default="none",
                help_text=(
                    "Tier 2: tracks AI generation lifecycle. 'none' = human-only (Tier 1). "
                    "'stale' = source content changed since last generation."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="generation_metadata",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text=(
                    "Per-field provenance written by Tier 2 generation. "
                    "Shape: {field_name: {source: 'ai'|'human'|'ai_edited', generated_at: iso, model: str}}. "
                    "Null for Tier 1 configs. Prevents silent overwrite of human-edited fields on refresh."
                ),
                null=True,
            ),
        ),
    ]
