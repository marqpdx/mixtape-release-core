import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("initiatives", "0009_agent_command_objects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentCommand",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sponsor_object_id", models.UUIDField(blank=True, null=True)),
                ("source", models.CharField(choices=[("mobile_initiatives", "Mobile Initiatives"), ("desktop_initiatives", "Desktop Initiatives")], default="mobile_initiatives", max_length=40)),
                ("capture_mode", models.CharField(choices=[("typed", "Typed"), ("voice", "Voice"), ("imported", "Imported"), ("pasted", "Pasted")], default="typed", max_length=20)),
                ("draft_session_id", models.CharField(blank=True, default="", max_length=255)),
                ("raw_input", models.TextField()),
                ("parsed_verb", models.CharField(blank=True, default="", max_length=40)),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("parsed_title", models.CharField(blank=True, default="", max_length=255)),
                ("parsed_summary", models.TextField(blank=True, default="")),
                ("parsed_fields", models.JSONField(blank=True, default=dict)),
                ("parse_metadata", models.JSONField(blank=True, default=dict)),
                ("generated_text", models.TextField(blank=True, default="")),
                ("needs_clarification", models.BooleanField(default=False)),
                ("clarification_reason", models.TextField(blank=True, default="")),
                ("edited_fields", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("parsed", "Parsed"), ("executed", "Executed"), ("failed", "Failed")], default="parsed", max_length=20)),
                ("executed_verb", models.CharField(blank=True, default="", max_length=40)),
                ("result_type", models.CharField(blank=True, choices=[("acknowledgment", "Acknowledgment"), ("generated_artifact", "Generated Artifact"), ("search_results", "Search Results")], default="", max_length=30)),
                ("result_payload", models.JSONField(blank=True, default=dict)),
                ("error_payload", models.JSONField(blank=True, default=dict)),
                ("follow_up_suggestions", models.JSONField(blank=True, default=list)),
                ("routing_metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="initiative_agent_commands", to=settings.AUTH_USER_MODEL)),
                ("initiative", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="agent_commands", to="initiatives.initiative")),
                ("sponsor_content_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="initiative_agent_commands", to="contenttypes.contenttype")),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [
                    models.Index(fields=["source", "-created_at"], name="init_agcmd_source_idx"),
                    models.Index(fields=["initiative", "-created_at"], name="initiatives_agentcmd_init_idx"),
                    models.Index(fields=["status", "-created_at"], name="init_agcmd_status_idx"),
                    models.Index(fields=["created_by", "-created_at"], name="initiatives_agentcmd_user_idx"),
                ],
            },
        ),
    ]
