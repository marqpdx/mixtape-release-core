# Generated for DB-0002 Crossroads Page — PublicPage model

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0024_add_circle_deliverable_intent"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicPage",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("pending_approval", "Pending Approval"),
                            ("published", "Published"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "draft_content",
                    models.JSONField(
                        default=dict,
                        help_text="Current draft slot values — not yet published.",
                    ),
                ),
                (
                    "published_content",
                    models.JSONField(
                        blank=True,
                        null=True,
                        help_text="Content snapshot as of last approval; served to anonymous readers.",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "published_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "group",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="public_page",
                        to="groups.group",
                    ),
                ),
            ],
            options={
                "app_label": "groups",
            },
        ),
    ]
