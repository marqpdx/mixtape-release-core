import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("initiatives", "0008_actionrun_running_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Note",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sponsor_object_id", models.UUIDField()),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("body", models.TextField()),
                ("capture_mode", models.CharField(choices=[("typed", "Typed"), ("voice", "Voice"), ("imported", "Imported"), ("pasted", "Pasted")], default="typed", max_length=20)),
                ("origin", models.CharField(choices=[("agent", "Agent"), ("manual", "Manual")], default="agent", max_length=20)),
                ("raw_input", models.TextField(blank=True, default="")),
                ("parsed_metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="initiative_notes", to=settings.AUTH_USER_MODEL)),
                ("initiative", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notes", to="initiatives.initiative")),
                ("sponsor_content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="initiative_notes", to="contenttypes.contenttype")),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [
                    models.Index(fields=["sponsor_content_type", "sponsor_object_id", "-created_at"], name="initiatives_note_sponsor_idx"),
                    models.Index(fields=["initiative", "-created_at"], name="initiatives_note_init_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sponsor_object_id", models.UUIDField()),
                ("title", models.CharField(max_length=255)),
                ("details", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("todo", "To do"), ("in_progress", "In progress"), ("done", "Done"), ("cancelled", "Cancelled")], default="todo", max_length=20)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("capture_mode", models.CharField(choices=[("typed", "Typed"), ("voice", "Voice"), ("imported", "Imported"), ("pasted", "Pasted")], default="typed", max_length=20)),
                ("origin", models.CharField(choices=[("agent", "Agent"), ("manual", "Manual")], default="agent", max_length=20)),
                ("raw_input", models.TextField(blank=True, default="")),
                ("parsed_metadata", models.JSONField(blank=True, default=dict)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_initiative_tasks", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_initiative_tasks", to=settings.AUTH_USER_MODEL)),
                ("initiative", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tasks", to="initiatives.initiative")),
                ("sponsor_content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="initiative_tasks", to="contenttypes.contenttype")),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [
                    models.Index(fields=["sponsor_content_type", "sponsor_object_id", "-created_at"], name="initiatives_task_sponsor_idx"),
                    models.Index(fields=["initiative", "-created_at"], name="initiatives_task_init_idx"),
                    models.Index(fields=["status", "due_at"], name="initiatives_task_status_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="reminder",
            name="capture_mode",
            field=models.CharField(choices=[("typed", "Typed"), ("voice", "Voice"), ("imported", "Imported"), ("pasted", "Pasted")], default="typed", max_length=20),
        ),
        migrations.AddField(
            model_name="reminder",
            name="origin",
            field=models.CharField(choices=[("agent", "Agent"), ("manual", "Manual")], default="agent", max_length=20),
        ),
        migrations.AddField(
            model_name="reminder",
            name="parsed_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="reminder",
            name="raw_input",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="reminder",
            name="sponsor_content_type",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="initiative_reminders", to="contenttypes.contenttype"),
        ),
        migrations.AddField(
            model_name="reminder",
            name="sponsor_object_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reminder",
            name="title",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="reminder",
            name="initiative",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reminders", to="initiatives.initiative"),
        ),
        migrations.AlterModelOptions(
            name="reminder",
            options={"ordering": ["remind_at"]},
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(fields=["sponsor_content_type", "sponsor_object_id", "remind_at"], name="initiatives_rem_sponsor_idx"),
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(fields=["initiative", "remind_at"], name="initiatives_rem_init_idx"),
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(fields=["status", "remind_at"], name="initiatives_rem_status_idx"),
        ),
    ]
