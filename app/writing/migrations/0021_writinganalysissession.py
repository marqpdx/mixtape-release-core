from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0020_writingsynopsis_atelier_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WritingAnalysisSession",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_revision_hash", models.CharField(db_index=True, max_length=71)),
                ("export_version", models.CharField(default="writing-analysis-export@v1", max_length=64)),
                ("planner_type", models.CharField(blank=True, default="", max_length=32)),
                ("planner_label", models.CharField(blank=True, default="", max_length=128)),
                ("status", models.CharField(choices=[("exported", "Exported"), ("analyzing", "Analyzing"), ("ready", "Ready"), ("approved", "Approved"), ("imported", "Imported"), ("failed", "Failed"), ("stale", "Stale")], db_index=True, default="exported", max_length=16)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("export_payload", models.JSONField(blank=True, default=dict)),
                ("suggestion_payload", models.JSONField(blank=True, default=dict)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="writing_analysis_sessions", to=settings.AUTH_USER_MODEL)),
                ("source_piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="analysis_sessions", to="writing.writingpiece")),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Writing Analysis Session",
                "verbose_name_plural": "Writing Analysis Sessions",
            },
        ),
        migrations.AddIndex(
            model_name="writinganalysissession",
            index=models.Index(fields=["source_piece", "created_at"], name="writing_wri_source__17e638_idx"),
        ),
        migrations.AddIndex(
            model_name="writinganalysissession",
            index=models.Index(fields=["status"], name="writing_wri_status_413bc8_idx"),
        ),
    ]
