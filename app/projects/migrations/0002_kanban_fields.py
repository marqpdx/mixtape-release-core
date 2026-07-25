from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


def seed_task_types(apps, schema_editor):
    TaskType = apps.get_model("projects", "TaskType")
    defaults = [
        ("Bug", "bug", "Something is broken or wrong, no matter how minor", 0),
        ("Request", "request", "A proposal to add or change something", 1),
        ("Question", "question", "Something that needs to be answered", 2),
        ("Research", "research", "We need more information on a topic", 3),
    ]
    for name, slug, description, position in defaults:
        TaskType.objects.create(
            name=name, slug=slug, description=description, position=position
        )


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. TaskType model
        migrations.CreateModel(
            name="TaskType",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["position", "name"]},
        ),

        # 2. New Task fields
        migrations.AddField(
            model_name="task",
            name="task_type",
            field=models.ForeignKey(
                "projects.TaskType",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="severity",
            field=models.CharField(
                max_length=20,
                choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
                default="low",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="timeliness",
            field=models.CharField(
                max_length=20,
                choices=[("pressing", "Pressing"), ("normal", "Normal"), ("eventually", "Eventually")],
                default="normal",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="assignee",
            field=models.ForeignKey(
                settings.AUTH_USER_MODEL,
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_tasks",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="sign_off_criteria",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="task",
            name="due_date",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="task",
            name="due_date_overridden",
            field=models.BooleanField(default=False),
        ),

        # 3. Seed task types
        migrations.RunPython(seed_task_types, migrations.RunPython.noop),
    ]
