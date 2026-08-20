# Generated manually for OCR spike shape-aware curation.

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("ocr_spike", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OcrSpikeShapingAttempt",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("shape_id", models.CharField(max_length=120)),
                ("shape_version", models.CharField(max_length=32)),
                ("model_name", models.CharField(blank=True, max_length=160)),
                ("input_text", models.TextField(blank=True)),
                ("output_json", models.JSONField(blank=True, default=dict)),
                ("output_markdown", models.TextField(blank=True)),
                ("validation_errors", models.JSONField(blank=True, default=list)),
                ("processing_time_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("processing", "Processing"), ("complete", "Complete"), ("failed", "Failed")], default="processing", max_length=16)),
                ("error_message", models.TextField(blank=True)),
                ("page", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shaping_attempts", to="ocr_spike.ocrspikepage")),
                ("selected_attempt", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shaping_attempts", to="ocr_spike.ocrspikerecognitionattempt")),
            ],
            options={"db_table": "ocr_spike_shaping_attempt", "ordering": ["-created_at"]},
        ),
    ]
