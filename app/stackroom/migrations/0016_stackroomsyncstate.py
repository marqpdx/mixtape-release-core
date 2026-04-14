from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("stackroom", "0015_puddlejump_canon_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="StackroomSyncState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("object_id", models.CharField(max_length=64)),
                ("adapter_name", models.CharField(db_index=True, max_length=64)),
                ("transport_mode", models.CharField(choices=[("local", "Local"), ("shadow", "Shadow"), ("remote", "Remote")], default="local", max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("synced", "Synced"), ("failed", "Failed"), ("deactivated", "Deactivated")], db_index=True, default="pending", max_length=16)),
                ("last_ingested_at", models.DateTimeField(blank=True, null=True)),
                ("last_synced_hash", models.CharField(blank=True, default="", max_length=64)),
                ("last_error", models.TextField(blank=True, default="")),
                ("stackroom_library_id", models.UUIDField(blank=True, null=True)),
                ("stackroom_source_file_id", models.UUIDField(blank=True, null=True)),
                ("stackroom_artifact_id", models.UUIDField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["content_type", "object_id"], name="stackroom_s_content_2df0fd_idx"),
                    models.Index(fields=["adapter_name", "status"], name="stackroom_s_adapter_d265a8_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("content_type", "object_id", "adapter_name"), name="uniq_stackroom_sync_state_object_adapter"),
                ],
            },
        ),
    ]
