import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0003_initiative_radar_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="InitiativeArtifact",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "initiative",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="initiative_artifacts",
                        to="initiatives.initiative",
                    ),
                ),
                (
                    "artifact_type",
                    models.CharField(
                        choices=[("doc_link", "Doc Link"), ("conversation_import", "Conversation Import")],
                        max_length=30,
                    ),
                ),
                ("label", models.CharField(max_length=200)),
                (
                    "doc_path",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="For doc_link: the puddlejump file path (e.g. pilots/weave-pilot.md).",
                        max_length=500,
                    ),
                ),
                (
                    "conversation_source",
                    models.CharField(
                        blank=True,
                        choices=[("claude", "Claude"), ("chatgpt", "ChatGPT"), ("other", "Other")],
                        default="",
                        help_text="For conversation_import: the originating tool.",
                        max_length=20,
                    ),
                ),
                (
                    "conversation_json",
                    models.JSONField(
                        blank=True,
                        help_text="Raw imported JSON stored as-is for future structured access.",
                        null=True,
                    ),
                ),
                (
                    "conversation_text",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Plain-text transcript generated at import time. Never AI-summarized in Phase 1.",
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Ordering within the initiative's artifact list. User-controlled.",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "created_at"],
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="initiativeartifact",
            index=models.Index(fields=["initiative", "position"], name="init_artifact_order_idx"),
        ),
    ]
