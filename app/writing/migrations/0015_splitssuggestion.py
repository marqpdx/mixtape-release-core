import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0014_writingpiece_wordcount_goal"),
    ]

    operations = [
        migrations.CreateModel(
            name="SplitSuggestion",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("ready", "Ready"),
                            ("shown", "Shown"),
                            ("accepted", "Accepted"),
                            ("dismissed", "Dismissed"),
                            ("declined", "Declined"),
                            ("superseded", "Superseded"),
                            ("executed", "Executed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "suggestions",
                    models.JSONField(
                        default=list,
                        help_text="List of {after_paragraph_index, rationale} objects from AI",
                    ),
                ),
                (
                    "word_count_at_suggestion",
                    models.PositiveIntegerField(
                        help_text="Word count at the time this suggestion was generated.",
                    ),
                ),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "piece",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="split_suggestions",
                        to="writing.writingpiece",
                    ),
                ),
            ],
            options={
                "verbose_name": "Split Suggestion",
                "verbose_name_plural": "Split Suggestions",
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
    ]
