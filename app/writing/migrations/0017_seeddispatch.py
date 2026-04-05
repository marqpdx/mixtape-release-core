# writing/migrations/0017_seeddispatch.py

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0016_leafplacement_leafcomment_placement_fk"),
    ]

    operations = [
        migrations.CreateModel(
            name="SeedDispatch",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "destination_type",
                    models.CharField(
                        choices=[
                            ("message", "Message"),
                            ("storyline", "Storyline"),
                            ("commons", "Commons"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                (
                    "destination_id",
                    models.UUIDField(
                        blank=True,
                        null=True,
                        help_text="Recipient user/group ID, or null for Commons",
                    ),
                ),
                (
                    "verb",
                    models.CharField(
                        choices=[("copy", "Copy"), ("move", "Move")],
                        max_length=8,
                    ),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[("delivered", "Delivered"), ("failed", "Failed")],
                        default="delivered",
                        max_length=16,
                    ),
                ),
                ("dispatched_at", models.DateTimeField()),
                (
                    "seed",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatches",
                        to="writing.seed",
                    ),
                ),
            ],
            options={
                "ordering": ["-dispatched_at"],
            },
        ),
        migrations.AddIndex(
            model_name="seeddispatch",
            index=models.Index(
                fields=["seed", "destination_type"],
                name="writing_seeddispatch_seed_dest_idx",
            ),
        ),
    ]
