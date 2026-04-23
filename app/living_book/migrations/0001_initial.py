import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("writing", "0025_rename_writing_wri_analysi_bbd3b1_idx_writing_wri_analysi_35ea8a_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LivingBook",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=500)),
                ("description", models.TextField(blank=True, default="")),
                ("sponsor_object_id", models.UUIDField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_living_books",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sponsor_content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sponsored_living_books",
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "trunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="living_books_as_trunk",
                        to="writing.writingpiece",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="livingbook",
            index=models.Index(fields=["trunk"], name="living_book_trunk_id_idx"),
        ),
        migrations.AddIndex(
            model_name="livingbook",
            index=models.Index(fields=["status"], name="living_book_status_idx"),
        ),
    ]
