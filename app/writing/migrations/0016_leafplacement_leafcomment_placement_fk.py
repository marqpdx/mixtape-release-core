# writing/migrations/0016_leafplacement_leafcomment_placement_fk.py

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0015_splitssuggestion"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Create LeafPlacement
        migrations.CreateModel(
            name="LeafPlacement",
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
                    "target_object_id",
                    models.UUIDField(),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("rescinded", "Rescinded")],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                ("rescinded_at", models.DateTimeField(blank=True, null=True)),
                ("visibility", models.CharField(default="members", max_length=16)),
                (
                    "leaf",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="placements",
                        to="writing.leaf",
                    ),
                ),
                (
                    "placed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leaf_placements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "target_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="leafplacement",
            index=models.Index(
                fields=["target_content_type", "target_object_id", "status"],
                name="writing_lea_target__idx",
            ),
        ),

        # 2. Create LeafPlacementReaction
        migrations.CreateModel(
            name="LeafPlacementReaction",
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
                ("reaction_name", models.CharField(max_length=50)),
                (
                    "placement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reactions",
                        to="writing.leafplacement",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("placement", "user", "reaction_name")},
            },
        ),
        migrations.AddIndex(
            model_name="leafplacementreaction",
            index=models.Index(
                fields=["placement", "reaction_name"],
                name="writing_lea_placeme_reaction_idx",
            ),
        ),

        # 3. Add new `placement` FK to LeafComment (nullable for migration safety)
        migrations.AddField(
            model_name="leafcomment",
            name="placement",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="comments",
                to="writing.leafplacement",
            ),
        ),

        # 4. Remove old `leaf` FK from LeafComment
        #    No production data to migrate (confirmed by spec).
        migrations.RemoveField(
            model_name="leafcomment",
            name="leaf",
        ),

        # 5. Make placement non-nullable now that leaf is gone
        migrations.AlterField(
            model_name="leafcomment",
            name="placement",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="comments",
                to="writing.leafplacement",
            ),
        ),
    ]
