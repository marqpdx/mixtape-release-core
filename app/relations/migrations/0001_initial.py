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
            name="RelationshipType",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(max_length=50, unique=True)),
                ("label", models.CharField(max_length=100)),
                ("inverse_label", models.CharField(blank=True, default="", max_length=100)),
                (
                    "domain",
                    models.CharField(
                        choices=[
                            ("structural", "Structural"),
                            ("editorial", "Editorial"),
                            ("social", "Social"),
                            ("commons", "Commons"),
                            ("initiative", "Initiative"),
                            ("spatial", "Spatial"),
                        ],
                        max_length=20,
                    ),
                ),
                ("is_directed", models.BooleanField(default=True)),
                ("allows_position", models.BooleanField(default=False)),
                ("allows_weight", models.BooleanField(default=False)),
                ("uses_lifecycle", models.BooleanField(default=True)),
                ("valid_source_types", models.JSONField(blank=True, default=list)),
                ("valid_target_types", models.JSONField(blank=True, default=list)),
            ],
            options={
                "ordering": ["domain", "slug"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Relationship",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_object_id", models.UUIDField()),
                ("target_object_id", models.UUIDField()),
                ("position", models.PositiveIntegerField(blank=True, null=True)),
                ("weight", models.FloatField(blank=True, null=True)),
                (
                    "lifecycle",
                    models.CharField(
                        choices=[
                            ("authored", "Authored"),
                            ("acknowledged", "Acknowledged"),
                            ("mutual", "Mutual"),
                        ],
                        default="authored",
                        max_length=20,
                    ),
                ),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("public", "Public"),
                            ("members", "Members"),
                            ("private", "Private"),
                        ],
                        default="public",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("archived", "Archived"),
                            ("pending", "Pending"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_relationships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "relationship_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="relationships",
                        to="relations.relationshiptype",
                    ),
                ),
                (
                    "source_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outgoing_relationships",
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "target_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="incoming_relationships",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "-created_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="RelationshipAnnotation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("body", models.TextField(blank=True, default="")),
                ("anchor_text", models.CharField(blank=True, default="", max_length=255)),
                (
                    "relationship",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="annotation",
                        to="relations.relationship",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="relationship",
            index=models.Index(
                fields=["source_content_type", "source_object_id"],
                name="relations_r_source__idx",
            ),
        ),
        migrations.AddIndex(
            model_name="relationship",
            index=models.Index(
                fields=["target_content_type", "target_object_id"],
                name="relations_r_target__idx",
            ),
        ),
        migrations.AddIndex(
            model_name="relationship",
            index=models.Index(
                fields=["relationship_type", "status"],
                name="relations_r_type_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="relationship",
            index=models.Index(
                fields=["source_content_type", "source_object_id", "relationship_type"],
                name="relations_r_source_type_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="relationship",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="active"),
                fields=[
                    "source_content_type",
                    "source_object_id",
                    "target_content_type",
                    "target_object_id",
                    "relationship_type",
                ],
                name="relations_unique_active_relationship",
            ),
        ),
    ]
