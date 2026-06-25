# commons/models.py

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent


User = get_user_model()


class CommonsItem(BaseContent):
    """
    A curated entry in the Crossroads Commons atlas.

    Inherits from BaseContent:
      id (UUID), title, summary, slug, body, submitted_by, author,
      sponsor GFK, tags/categories via GenericRelation, published_at,
      created_at, updated_at, deleted_at.
    """

    class ItemType(models.TextChoices):
        PERSON = "person", "Person"
        ORGANIZATION = "organization", "Organization"
        GROUP = "group", "Group"
        PROJECT = "project", "Project"
        PLACE = "place", "Place"
        EVENT = "event", "Event"

    class CurationStatus(models.TextChoices):
        CAPTURED = "captured", "Captured"
        IN_CURATION = "in_curation", "In Curation"
        READY = "ready", "Ready for Review"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    # Type
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        blank=True,
        default="",
    )

    # Curation workflow
    curation_status = models.CharField(
        max_length=20,
        choices=CurationStatus.choices,
        default=CurationStatus.CAPTURED,
        db_index=True,
    )

    # Human recommendation
    recommended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_recommendations",
    )
    why_recommended = models.TextField(blank=True, default="")

    # External links
    website = models.URLField(max_length=500, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_links = models.JSONField(default=list, blank=True)
    instagram = models.URLField(max_length=500, blank=True, default="")
    youtube = models.URLField(max_length=500, blank=True, default="")
    rss = models.URLField(max_length=500, blank=True, default="")

    # Geographic
    location_name = models.CharField(max_length=255, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Extraction
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Original submitted URL",
    )
    extracted_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw extraction output from Inkwell",
    )
    additional_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible metadata (hours, pricing, etc.)",
    )

    # Curation tracking
    curated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_curations",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_approvals",
    )

    # Founder (text for now, Filament relationship later)
    founder = models.CharField(max_length=255, blank=True, default="")

    class Meta(BaseContent.Meta):
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["curation_status"]),
            models.Index(fields=["item_type"]),
            models.Index(fields=["curation_status", "-created_at"]),
        ]

    def __str__(self):
        return self.title or f"CommonsItem {self.pk}"


# ============================================================================
# Leaf — Commons content unit (ADR-0049; moved from app/writing/, D19)
# ============================================================================

class Leaf(BaseModel):
    """
    First-class Commons content unit (formerly the Storyline content unit;
    Storyline is superseded by ADR-0049 — see commons-adr.md D1/D2).
    Sits between Seed (private capture) and WritingPiece (structured publication).

    Two kinds (one model):
    - Native Leaf: original content written for Commons
    - Reference Leaf: curated card pointing to other content via GFK
      (source_content_type / source_object_id set)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leaves"
    )

    # Content
    body_text = models.TextField(blank=True, default="")
    body_json = models.JSONField(
        default=dict,
        help_text="ProseMirror content for rich text + images",
    )
    caption = models.TextField(
        blank=True, default="",
        help_text="Author's original commentary (especially for reference Leafs)",
    )

    LEAF_KIND_CHOICES = [
        ("text", "Text"),
        ("image", "Image"),
        ("link", "Link"),
        ("voice", "Voice"),
    ]
    kind = models.CharField(max_length=16, choices=LEAF_KIND_CHOICES, default="text")

    # Provenance
    origin_seed = models.ForeignKey(
        "writing.Seed", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="promoted_leaves",
    )
    promoted_to = models.OneToOneField(
        "writing.WorkingDocument", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leaf_origin",
    )

    # Media
    audio_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="voice_leaves",
    )
    image_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="image_leaves",
    )
    link_url = models.URLField(null=True, blank=True)
    link_preview = models.JSONField(
        default=dict, blank=True,
        help_text="Cached link preview metadata (title, image, description)",
    )

    # Reference Leaf — GFK to source content (WritingPiece, Course, etc.)
    source_content_type = models.ForeignKey(
        ContentType, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    source_object_id = models.UUIDField(null=True, blank=True)
    source = GenericForeignKey("source_content_type", "source_object_id")

    # Visibility & publishing
    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("followers", "Followers"),
        ("private", "Private"),
    ]
    visibility = models.CharField(
        max_length=16, choices=VISIBILITY_CHOICES, default="public",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    # Commons (ADR-0049) — Place anchor. Required for Commons-shared Leaves
    # (library_only=False), optional for library-only Leaves; enforced at
    # the service layer when state transitions to closed (OQ-5).
    place = models.ForeignKey(
        "tapestry.Place",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="leaves",
    )

    # When the session occurred — distinct from created_at (note may be written later)
    occurred_at = models.DateTimeField(null=True, blank=True)

    # Open / Closed lifecycle (ADR-0049 D5)
    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Open"),
        (STATE_CLOSED, "Closed"),
    ]
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=STATE_OPEN)

    # Whether the Closed Leaf is shared to Commons or kept in personal library
    library_only = models.BooleanField(default=False)

    # Feeling state — future-facing, undecided; field reserved but not exposed in Phase 1 (D14)
    feeling_state = models.CharField(max_length=30, blank=True, default="")

    # Intent — future-facing; field reserved but not exposed in Phase 1 (D15)
    intent_primary = models.CharField(max_length=30, blank=True, default="")
    intent_secondary = models.CharField(max_length=30, blank=True, default="")

    class Meta(BaseModel.Meta):
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["author", "-published_at"]),
            models.Index(fields=["author", "kind"]),
        ]

    @property
    def is_reference(self):
        return self.source_content_type_id is not None

    @property
    def is_published(self):
        return self.published_at is not None

    def __str__(self):
        ref = " (ref)" if self.is_reference else ""
        return f"Leaf<{self.kind}{ref}> by {self.author_id}"


class LeafEntry(BaseModel):
    """
    Ordered content entries within a Leaf (ADR-0049 D6). The `shared` flag
    governs trim-for-sharing: False entries stay in the author's library
    (D7) and are excluded from the Commons-facing view of the Leaf.

    Uses `files.StoredFile` for media, matching Leaf's own convention —
    the ADR's draft spec named `stash.StashFile`, but no `stash` app exists
    in this codebase; `files.StoredFile` is the live equivalent.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    leaf = models.ForeignKey(
        Leaf,
        on_delete=models.CASCADE,
        related_name="entries",
    )

    KIND_TEXT = "text"
    KIND_IMAGE = "image"
    KIND_VOICE = "voice"
    KIND_CHOICES = [
        (KIND_TEXT, "Text"),
        (KIND_IMAGE, "Image"),
        (KIND_VOICE, "Voice"),
    ]
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    position = models.PositiveIntegerField()

    # Content by kind
    body_text = models.TextField(blank=True, default="")
    body_json = models.JSONField(null=True, blank=True)  # ProseMirror rich text
    image_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leaf_entry_images",
    )
    audio_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leaf_entry_audio",
    )

    # Trim-for-sharing: False = library only, excluded from Commons view
    shared = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["position"]

    def __str__(self):
        return f"LeafEntry<{self.kind}> #{self.position} on {self.leaf_id}"


