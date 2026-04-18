from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0021_writinganalysissession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WritingSuggestedRevision",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_revision_hash", models.CharField(db_index=True, max_length=71)),
                ("derivation_type", models.CharField(choices=[("suggested_revision", "Suggested Revision")], default="suggested_revision", max_length=32)),
                ("analysis_session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="suggested_revisions", to="writing.writinganalysissession")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_suggested_revisions", to=settings.AUTH_USER_MODEL)),
                ("source_piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="suggested_revisions_as_source", to="writing.writingpiece")),
                ("suggested_piece", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="suggested_revision_lineage", to="writing.writingpiece")),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Writing Suggested Revision",
                "verbose_name_plural": "Writing Suggested Revisions",
            },
        ),
        migrations.AddIndex(
            model_name="writingsuggestedrevision",
            index=models.Index(fields=["source_piece", "created_at"], name="writing_wri_source__ad2123_idx"),
        ),
        migrations.AddIndex(
            model_name="writingsuggestedrevision",
            index=models.Index(fields=["analysis_session"], name="writing_wri_analysi_5ab9fb_idx"),
        ),
        migrations.AddIndex(
            model_name="writingsuggestedrevision",
            index=models.Index(fields=["source_revision_hash"], name="writing_wri_source__2bf4e7_idx"),
        ),
    ]
