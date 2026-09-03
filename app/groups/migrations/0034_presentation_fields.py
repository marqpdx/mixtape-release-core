from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0033_add_generation_fields_to_public_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouppublicconfig",
            name="typography_setting",
            field=models.CharField(
                choices=[("journal", "Journal"), ("notice", "Notice")],
                default="journal",
                help_text="Tier 1: 'journal' (serif) or 'notice' (sans). Governs font scale and spacing rhythm.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="template_id",
            field=models.CharField(
                blank=True,
                choices=[
                    ("masthead", "Masthead"),
                    ("ledger", "Ledger"),
                    ("atlas", "Atlas"),
                    ("docket", "Docket"),
                ],
                default="",
                help_text="Tier 2+: template layout. Empty → Masthead.",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="palette_id",
            field=models.CharField(
                blank=True,
                choices=[
                    ("quarto", "Quarto"),
                    ("foolscap", "Foolscap"),
                    ("pigment", "Pigment"),
                    ("common", "Common"),
                ],
                default="",
                help_text="Tier 2+: tenant palette. Empty → platform default.",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="font_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Tier 2+: font ID from the ten-font shortlist. Empty → typography_setting default.",
                max_length=50,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="grouppublicconfig",
            name="presentation_overrides",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text=(
                    "Tier 3 only. Serialized action vocabulary result: palette hex per role/mode, "
                    "zone order/variants, density. Versioned for Look restoration."
                ),
                null=True,
            ),
        ),
    ]
