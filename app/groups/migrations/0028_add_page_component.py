from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0027_publicpage_layout_template_needs_review"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageComponent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="groups.publicpage",
                    ),
                ),
                (
                    "slot",
                    models.CharField(
                        max_length=64,
                        help_text="Named slot on the page layout (e.g. 'about', 'links', 'cta').",
                    ),
                ),
                (
                    "component_type",
                    models.CharField(
                        max_length=20,
                        choices=[
                            ("text", "Text"),
                            ("image", "Image"),
                            ("link", "Link"),
                            ("callout", "Callout"),
                        ],
                    ),
                ),
                ("content_json", models.JSONField(default=dict)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "app_label": "groups",
                "ordering": ["slot", "sort_order", "created_at"],
            },
        ),
    ]
