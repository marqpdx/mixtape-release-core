from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0023_rename_writing_wri_source__17e638_idx_writing_wri_source__18a8ff_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WritingFidelityReport",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_revision_hash", models.CharField(db_index=True, max_length=71)),
                ("report_version", models.CharField(default="writing-fidelity-report@v1", max_length=64)),
                ("report_payload", models.JSONField(blank=True, default=dict)),
                ("analysis_session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fidelity_reports", to="writing.writinganalysissession")),
                ("source_piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fidelity_reports_as_source", to="writing.writingpiece")),
                ("suggested_piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fidelity_reports_as_suggested", to="writing.writingpiece")),
                ("suggested_revision", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="fidelity_report", to="writing.writingsuggestedrevision")),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Writing Fidelity Report",
                "verbose_name_plural": "Writing Fidelity Reports",
            },
        ),
        migrations.AddIndex(
            model_name="writingfidelityreport",
            index=models.Index(fields=["analysis_session"], name="writing_wri_analysi_bbd3b1_idx"),
        ),
        migrations.AddIndex(
            model_name="writingfidelityreport",
            index=models.Index(fields=["source_piece", "created_at"], name="writing_wri_source__ae3745_idx"),
        ),
        migrations.AddIndex(
            model_name="writingfidelityreport",
            index=models.Index(fields=["suggested_piece"], name="writing_wri_suggest_e2f3b4_idx"),
        ),
        migrations.AddIndex(
            model_name="writingfidelityreport",
            index=models.Index(fields=["source_revision_hash"], name="writing_wri_source__95b2b0_idx"),
        ),
    ]
