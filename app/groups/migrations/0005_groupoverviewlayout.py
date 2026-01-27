from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0004_group_emblem"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupOverviewLayout",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("layout_version", models.CharField(default="1", max_length=16)),
                ("blocks", models.JSONField(default=list)),
                ("group", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="overview_layout", to="groups.group")),
            ],
            options={
                "ordering": ("-updated_at",),
            },
        ),
    ]
