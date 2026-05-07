import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("console", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        # EC-B7 — AgentPersona: AI tone/voice artifact, sponsor-polymorphic
        migrations.CreateModel(
            name="AgentPersona",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("sponsor_content_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="agent_personas",
                    to="contenttypes.contenttype",
                )),
                ("sponsor_object_id", models.UUIDField()),
                ("name", models.CharField(max_length=128)),
                ("role", models.CharField(max_length=128)),
                ("tone_summary", models.TextField()),
                ("tone_tags", models.JSONField(default=list)),
                ("constraints", models.JSONField(default=list)),
                ("writing_sample", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["name"],
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="agentpersona",
            index=models.Index(
                fields=["sponsor_content_type", "sponsor_object_id"],
                name="agentpersona_sponsor_idx",
            ),
        ),
    ]
