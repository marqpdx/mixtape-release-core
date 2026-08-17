import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("groups", "0031_add_catalyst_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalystParseJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("phase1_complete", "Phase 1 Complete"),
                        ("analyzing", "Analyzing"),
                        ("complete", "Complete"),
                        ("failed", "Failed"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=32,
                )),
                ("uploaded_files", models.JSONField(default=list)),
                ("client_context", models.TextField(blank=True)),
                ("phase1_results", models.JSONField(default=dict)),
                ("phase2_results", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("notified", models.BooleanField(default=False)),
                ("created_by", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="catalyst_parse_jobs",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("group", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="parse_jobs",
                    to="groups.group",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
