# Generated manually for the isolated OCR spike app.

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OcrSpikeArtifact",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_filename", models.CharField(max_length=255)),
                ("source_file_path", models.CharField(max_length=512)),
                ("content_type", models.CharField(blank=True, max_length=120)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("page_count", models.PositiveIntegerField(blank=True, null=True)),
                ("privacy_sensitivity", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("complete", "Complete")], default="medium", max_length=16)),
                ("status", models.CharField(choices=[("uploaded", "Uploaded"), ("preparing", "Preparing"), ("recognizing", "Recognizing"), ("ready_for_review", "Ready for review"), ("complete", "Complete"), ("failed", "Failed")], default="uploaded", max_length=32)),
                ("error_message", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ocr_spike_artifacts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "ocr_spike_artifact", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OcrSpikePage",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("page_number", models.PositiveIntegerField()),
                ("image_path", models.CharField(blank=True, max_length=512)),
                ("width", models.PositiveIntegerField(blank=True, null=True)),
                ("height", models.PositiveIntegerField(blank=True, null=True)),
                ("preparation_status", models.CharField(choices=[("pending", "Pending"), ("ready", "Ready"), ("failed", "Failed")], default="pending", max_length=16)),
                ("artifact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pages", to="ocr_spike.ocrspikeartifact")),
            ],
            options={"db_table": "ocr_spike_page", "ordering": ["page_number"], "unique_together": {("artifact", "page_number")}},
        ),
        migrations.CreateModel(
            name="OcrSpikeRecognitionAttempt",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("local", "Local"), ("cloud", "Cloud")], max_length=16)),
                ("engine_name", models.CharField(blank=True, max_length=120)),
                ("raw_text", models.TextField(blank=True)),
                ("raw_result_json", models.JSONField(blank=True, default=dict)),
                ("confidence_summary", models.JSONField(blank=True, default=dict)),
                ("processing_time_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("processing", "Processing"), ("complete", "Complete"), ("failed", "Failed")], default="processing", max_length=16)),
                ("error_message", models.TextField(blank=True)),
                ("page", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attempts", to="ocr_spike.ocrspikepage")),
            ],
            options={"db_table": "ocr_spike_recognition_attempt", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OcrSpikeEvaluation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("final_text", models.TextField(blank=True)),
                ("outcome", models.CharField(choices=[("accepted_local", "Accepted local"), ("corrected_local", "Corrected local"), ("accepted_cloud", "Accepted cloud"), ("corrected_cloud", "Corrected cloud"), ("unreadable", "Unreadable"), ("skipped", "Skipped")], max_length=32)),
                ("quality_rating", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("correction_effort", models.CharField(blank=True, choices=[("none", "None"), ("minor", "Minor"), ("heavy", "Heavy"), ("not_worth_it", "Not worth it")], max_length=32)),
                ("search_summary", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("page", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="evaluation", to="ocr_spike.ocrspikepage")),
                ("selected_attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evaluations", to="ocr_spike.ocrspikerecognitionattempt")),
            ],
            options={"db_table": "ocr_spike_evaluation", "ordering": ["page__artifact_id", "page__page_number"]},
        ),
        migrations.CreateModel(
            name="OcrSpikeFeedbackNote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("screen", models.CharField(choices=[("upload", "Upload"), ("processing", "Processing"), ("curation", "Curation"), ("complete", "Complete")], max_length=32)),
                ("note", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("artifact", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="feedback_notes", to="ocr_spike.ocrspikeartifact")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ocr_spike_feedback_notes", to=settings.AUTH_USER_MODEL)),
                ("page", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="feedback_notes", to="ocr_spike.ocrspikepage")),
            ],
            options={"db_table": "ocr_spike_feedback_note", "ordering": ["-created_at"]},
        ),
    ]
