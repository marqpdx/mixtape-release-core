from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0026_add_tenant_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="publicpage",
            name="layout_template",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("standard", "Standard"),
                    ("hero", "Hero"),
                    ("focus", "Focus"),
                    ("directory", "Directory"),
                ],
                default="standard",
            ),
        ),
        migrations.AddField(
            model_name="publicpage",
            name="needs_review",
            field=models.BooleanField(
                default=False,
                help_text="Steward-flagged: this page needs attention. Does not remove it from public view.",
            ),
        ),
    ]
