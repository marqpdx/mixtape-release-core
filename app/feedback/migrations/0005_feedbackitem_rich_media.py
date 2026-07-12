from __future__ import annotations

import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0004_alter_feedbackitem_status"),
        ("files", "0001_initial"),
        ("media_capture", "0002_add_purpose_to_mediacapture"),
    ]

    operations = [
        migrations.AddField(
            model_name="feedbackitem",
            name="work_area",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="feedbackitem",
            name="voice_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="feedback_items",
                to="files.storedfile",
            ),
        ),
        migrations.AddField(
            model_name="feedbackitem",
            name="voice_transcript",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="feedbackitem",
            name="media_capture",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="feedback_items",
                to="media_capture.mediacapture",
            ),
        ),
        migrations.CreateModel(
            name="FeedbackAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "feedback_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="feedback.feedbackitem",
                    ),
                ),
                (
                    "stored_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback_attachments",
                        to="files.storedfile",
                    ),
                ),
            ],
        ),
    ]
