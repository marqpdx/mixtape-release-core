# storyboard/models.py
#
# The shared arrangement layer (decisions/folio/folio-storyboard-review.md
# §5, puddlejump): a Storyboard is the whole; StoryboardItem is a position
# in its tree. Fiction is the first real consumer (fiction_v1 grammar,
# storyboard/grammars.py); Issue is the next after this proves out.
#
# Deliberately NOT built here yet (later phases, see
# decisions/folio/folio-storyboard-build-handoff.md §4):
# Participation (Phase 7), Seam (no phase assigned), SurfaceState (Phase 6).

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class Storyboard(BaseModel):
    """
    The whole arrangement -- e.g. one novel-in-progress. Folio stays a
    habitat and feeds a Storyboard; it never contains one (review §4).
    """

    KIND_CHOICES = [
        ("writing", "Writing"),
        # "course" / "issue" / "collection" are later consumers (review §7).
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="writing")
    grammar = models.CharField(
        max_length=50,
        help_text='Registry key (e.g. "fiction_v1") resolved against storyboard/grammars.py -- not a Contour shape.',
    )
    title = models.CharField(max_length=255, blank=True, default="")
    head = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional rich body (TipTap/ProseMirror) describing the whole Storyboard.",
    )

    folio = models.ForeignKey(
        "folio.Folio",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="storyboards",
        help_text="Optional -- this Storyboard draws from that Folio's FolioNotes, doesn't own them.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_storyboards",
        help_text="Real owner FK -- not derived from the optional folio link.",
    )

    # Polymorphic sponsor (User for personal context, Group for group
    # context). Persisted at creation time, validated against the creating
    # user's authority in that context. Never derived from the current URL
    # (build-handoff §2a). Every Scene's WritingPiece inherits this sponsor.
    sponsor_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="+"
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    locked = models.BooleanField(
        default=False,
        help_text="Set by a domain companion later (e.g. Issue publication). Unused by Writing for now.",
    )

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["created_by"]),
            models.Index(fields=["sponsor_content_type", "sponsor_object_id"]),
        ]

    def __str__(self):
        return self.title or f"Storyboard<{self.kind}:{self.grammar}> {self.id}"


class StoryboardItem(BaseModel):
    """
    A position in a Storyboard's tree. The general heterogeneous-reference
    GFK lives here and only here -- this consolidates the ContentType/GFK
    triplet the Phase 0 findings doc found hand-rolled four times
    (CollectionItem, Issue.sponsor, Leaf.source, LeafPlacement.target).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    storyboard = models.ForeignKey(
        Storyboard, on_delete=models.CASCADE, related_name="items"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    rank = models.PositiveIntegerField(
        default=0,
        help_text="Ordering among siblings -- canonical authored order. Changing it changes the work.",
    )
    level = models.CharField(
        max_length=30,
        help_text='Which grammar level this item occupies (e.g. "part"/"chapter"/"scene" for fiction_v1). Validated against the storyboard\'s grammar at the service layer, not hardcoded here.',
    )
    title = models.CharField(max_length=255, blank=True, default="")

    # Optional pointer to canonical material; null for purely structural
    # items (a Part that's just a grouping has no reference; a Scene's
    # reference points at its WritingPiece).
    reference_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reference_object_id = models.UUIDField(null=True, blank=True)
    reference = GenericForeignKey("reference_content_type", "reference_object_id")

    head = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional rich body (e.g. Chapter synopsis, section introduction).",
    )

    class Meta(BaseModel.Meta):
        ordering = ["rank"]
        indexes = [
            models.Index(fields=["storyboard", "parent", "rank"]),
            models.Index(fields=["reference_content_type", "reference_object_id"]),
        ]

    def __str__(self):
        return f"StoryboardItem<{self.level}> {self.title or self.id} (Storyboard {self.storyboard_id})"
