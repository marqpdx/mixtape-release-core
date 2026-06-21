import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_encrypt_chatmessage_text"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserDeviceSession",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("device_id", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("device_name", models.CharField(blank=True, max_length=128)),
                ("platform", models.CharField(
                    choices=[("web", "Web"), ("desktop", "Desktop"), ("ios", "iOS"), ("android", "Android")],
                    default="web",
                    max_length=16,
                )),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="device_sessions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user", "is_active"], name="chat_userdev_user_id_isactive_idx"),
                    models.Index(fields=["user", "-last_seen_at"], name="chat_userdev_user_id_lastseen_idx"),
                ],
            },
        ),
    ]
