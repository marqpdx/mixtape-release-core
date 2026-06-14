import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("almanac", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BridgeSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("room_name", models.CharField(max_length=255, unique=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                (
                    "occurrence",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bridge_session",
                        to="almanac.eventoccurrence",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
    ]
