import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0015_stackroom_library_id"),
    ]

    operations = [
        # EC-B6 — GroupContext: 1:1 extension of groups.Group
        migrations.CreateModel(
            name="GroupContext",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("group", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="context",
                    to="groups.group",
                )),
                ("founding_story", models.TextField(blank=True)),
                ("non_negotiables", models.JSONField(default=list)),
                ("voice_description", models.TextField(blank=True)),
                ("outward_feel", models.TextField(blank=True)),
                ("context_health_score", models.IntegerField(default=0)),
                ("last_prompted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Group Context",
            },
        ),
    ]
