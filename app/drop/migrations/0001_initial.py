# Generated manually 2026-06-12

import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Drop",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("handle", models.SlugField(max_length=100)),
                ("content", models.TextField()),
                ("object_id", models.UUIDField()),
                ("weight", models.CharField(
                    choices=[("pinned", "Pinned"), ("standard", "Standard"), ("social", "Social")],
                    default="standard",
                    max_length=16,
                )),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("event_date", models.DateField(blank=True, null=True)),
                ("related_handle", models.CharField(blank=True, max_length=200, null=True)),
                ("almanac_event_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("content_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="contenttypes.contenttype",
                )),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="drops",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [
                    models.Index(fields=["content_type", "object_id", "is_archived"], name="drop_drop_ct_oid_arch_idx"),
                    models.Index(fields=["weight", "is_archived"], name="drop_drop_weight_arch_idx"),
                    models.Index(fields=["expires_at"], name="drop_drop_expires_idx"),
                    models.Index(fields=["handle"], name="drop_drop_handle_idx"),
                ],
            },
        ),
    ]
