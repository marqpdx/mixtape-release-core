# workbench/models.py

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.models import BaseContent


class WorkingItemStatus(models.TextChoices):
    ASSEMBLING = "assembling", "Assembling"
    READY = "ready", "Ready"
    PROMOTED = "promoted", "Promoted"
    PARKED = "parked", "Parked"
    ARCHIVED = "archived", "Archived"


class WorkingItem(BaseContent):
    """
    Curated bundle of raw Pieces assembled for promotion to a WritingPiece.
    Inherits: UUID pk, sponsor GFK, author FK, tags/categories GenericRelations,
              slug lifecycle (BaseContent → BaseData → BaseModel).
    """

    # Primary editing surface (TipTap/ProseMirror JSON)
    body_json = models.JSONField(
        default=dict,
        help_text="TipTap/ProseMirror document. Seeded from member Pieces on creation.",
    )

    status = models.CharField(
        max_length=16,
        choices=WorkingItemStatus.choices,
        default=WorkingItemStatus.ASSEMBLING,
        db_index=True,
    )

    # Autosave tracking — mirrors WorkingDocument pattern
    last_saved_at = models.DateTimeField(null=True, blank=True)
    auto_save_count = models.PositiveIntegerField(default=0)

    # Promotion provenance
    promoted_to = models.ForeignKey(
        "writing.WritingPiece",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sourced_from_working_items",
    )
    promoted_at = models.DateTimeField(null=True, blank=True)

    # Provisional destination kind (post, article, dispatch, etc.)
    target_writing_kind = models.CharField(max_length=20, blank=True)

    # Fork lock — assembly order immutable once body editing begins
    body_editing_started = models.BooleanField(
        default=False,
        help_text="Set True on first body_json edit. Locks WorkingItemMembership position reordering.",
    )

    # Promotion gates
    spellcheck_passed = models.BooleanField(default=False)
    spellcheck_passed_at = models.DateTimeField(null=True, blank=True)
    promotion_gates = models.JSONField(
        default=dict,
        blank=True,
        help_text="Map of gate_name → passed (bool). Extensible.",
    )

    class Meta(BaseContent.Meta):
        ordering = ["-updated_at"]

    def __str__(self):
        return f"WorkingItem<{self.status}>: {self.title or 'Untitled'}"


class WorkingItemMembership(models.Model):
    """
    Provenance record linking a Piece to a WorkingItem.
    Never deleted after promotion — permanent audit trail.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    working_item = models.ForeignKey(
        WorkingItem,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    # Polymorphic link to the source Piece (Seed, Leaf, MillDraft, FeedbackItem, etc.)
    piece_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    piece_object_id = models.UUIDField()
    piece = GenericForeignKey("piece_content_type", "piece_object_id")

    # Content of the Piece at time of membership creation (stitched into body_json)
    content_snapshot = models.TextField(
        help_text="Content of the Piece at assembly time. Immutable after creation.",
    )

    position = models.PositiveIntegerField(
        default=0,
        help_text="Assembly order (0-indexed). Read-only once body_editing_started=True on WorkingItem.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["working_item", "piece_content_type", "piece_object_id"],
                name="workbench_membership_unique_piece_per_item",
            )
        ]
        indexes = [
            models.Index(fields=["piece_content_type", "piece_object_id"]),
        ]

    def __str__(self):
        return (
            f"WorkingItemMembership<{self.working_item_id}> "
            f"← {self.piece_content_type.model}:{self.piece_object_id} pos={self.position}"
        )
