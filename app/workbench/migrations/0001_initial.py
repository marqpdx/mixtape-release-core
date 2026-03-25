# workbench/migrations/0001_initial.py

import uuid

import django.db.models.deletion
import fundamentals.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("writing", "0011_leaf_leafcomment_leaf_writing_lea_author__836cc6_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkingItem",
            fields=[
                # BaseModel fields
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                # BaseData fields
                ("summary", models.TextField(blank=True, default="")),
                ("title", models.CharField(blank=True, default="", max_length=100)),
                ("slug", models.SlugField(default=fundamentals.models.default_slug, editable=False, max_length=64)),
                ("slug_is_custom", models.BooleanField(default=False, help_text="If True, the slug will not auto-regenerate from title.")),
                ("slug_history", models.JSONField(blank=True, default=list, help_text="Previous slugs for optional redirects (leave empty for now).")),
                # BaseContent fields
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)),
                ("author_name", models.CharField(blank=True, default="", max_length=255)),
                ("body", models.TextField(blank=True, default="")),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("sponsor_object_id", models.UUIDField()),
                # WorkingItem-specific fields
                ("body_json", models.JSONField(default=dict, help_text="TipTap/ProseMirror document. Seeded from member Pieces on creation.")),
                ("status", models.CharField(
                    choices=[
                        ("assembling", "Assembling"),
                        ("ready", "Ready"),
                        ("promoted", "Promoted"),
                        ("parked", "Parked"),
                        ("archived", "Archived"),
                    ],
                    db_index=True,
                    default="assembling",
                    max_length=16,
                )),
                ("last_saved_at", models.DateTimeField(blank=True, null=True)),
                ("auto_save_count", models.PositiveIntegerField(default=0)),
                ("promoted_at", models.DateTimeField(blank=True, null=True)),
                ("target_writing_kind", models.CharField(blank=True, max_length=20)),
                ("body_editing_started", models.BooleanField(
                    default=False,
                    help_text="Set True on first body_json edit. Locks WorkingItemMembership position reordering.",
                )),
                ("spellcheck_passed", models.BooleanField(default=False)),
                ("spellcheck_passed_at", models.DateTimeField(blank=True, null=True)),
                ("promotion_gates", models.JSONField(blank=True, default=dict, help_text="Map of gate_name → passed (bool). Extensible.")),
                # FK fields
                ("author", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="authored_workingitems",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("promoted_to", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="sourced_from_working_items",
                    to="writing.writingpiece",
                )),
                ("sponsor_content_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to="contenttypes.contenttype",
                )),
                ("submitted_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="submitted_workingitems",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-updated_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="WorkingItemMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("piece_object_id", models.UUIDField()),
                ("content_snapshot", models.TextField(help_text="Content of the Piece at assembly time. Immutable after creation.")),
                ("position", models.PositiveIntegerField(
                    default=0,
                    help_text="Assembly order (0-indexed). Read-only once body_editing_started=True on WorkingItem.",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("piece_content_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+",
                    to="contenttypes.contenttype",
                )),
                ("working_item", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="memberships",
                    to="workbench.workingitem",
                )),
            ],
            options={
                "ordering": ["position"],
            },
        ),
        migrations.AddConstraint(
            model_name="workingitem",
            constraint=models.UniqueConstraint(
                fields=["sponsor_content_type", "sponsor_object_id", "slug"],
                name="workbench_workingitem_slug_sponsor_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="workingitem",
            index=models.Index(
                fields=["sponsor_content_type", "sponsor_object_id"],
                name="workbench_wi_sponsor_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workingitem",
            index=models.Index(
                fields=["sponsor_content_type", "sponsor_object_id", "slug"],
                name="workbench_wi_sponsor_slug_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workingitem",
            index=models.Index(
                fields=["author", "-created_at"],
                name="workbench_wi_author_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workingitem",
            index=models.Index(
                fields=["submitted_by", "-created_at"],
                name="workbench_wi_submitted_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="workingitemmembership",
            constraint=models.UniqueConstraint(
                fields=["working_item", "piece_content_type", "piece_object_id"],
                name="workbench_membership_unique_piece_per_item",
            ),
        ),
        migrations.AddIndex(
            model_name="workingitemmembership",
            index=models.Index(
                fields=["piece_content_type", "piece_object_id"],
                name="workbench_membership_piece_idx",
            ),
        ),
    ]
