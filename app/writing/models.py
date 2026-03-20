# writing/models.py

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import CheckConstraint, Q, Max
from django.utils import timezone

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent
from mixtape.constants import PROVISIONAL_SLUG_PREFIX
from utils.writing.writing_utils import count_words_in_prosemirror
from writing.choices import ContentStatus
from publishing.models import BaseVersion


User = get_user_model()

def is_provisional_slug(slug: str | None) -> bool:
    return bool(slug and slug.startswith(PROVISIONAL_SLUG_PREFIX))


    # Add a mixin for publishable content

class PublishableContentMixin(models.Model):
    """Mixin for content that goes through publish workflow"""
    status = models.CharField(
        max_length=20,
        choices=ContentStatus.choices,
        default=ContentStatus.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class WritingPieceManager(models.Manager):
    def drafts(self): return self.filter(status="draft")
    def published(self): return self.filter(status="published")
    def scheduled(self): return self.filter(status="scheduled")
    def announcements(self): return self.filter(writing_kind="announcement")
    def pinned(self): return self.filter(pinned_at__isnull=False)
    def for_group(self, group):
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(type(group))
        return self.filter(sponsor_content_type=ct, sponsor_object_id=group.id)


class WritingPiece(BaseContent, PublishableContentMixin):
    """
    Unified writing model (draft|scheduled|published|archived).
    Canonical entity; autosave lives in WritingWorkingCopy.
    """
    body_json = models.JSONField(
        help_text="TipTap/ProseMirror content",
        default=dict,
    )

    writing_kind = models.CharField(
        max_length=20,
        choices=[
            ("post", "Post"),
            ("article", "Article"),
            ("dispatch", "Dispatch"),
            ("forum", "Forum Post"),
            ("announcement", "Announcement"),
            ("almanac", "Almanac"),
            ("page", "Page"),
            ("other", "Other"),
        ],
        default="post",
    )

    class AddressedTo(models.TextChoices):
        PUBLIC = "public", "Public"
        CROSSROADS = "crossroads", "Crossroads"
        SELF = "self", "Self"

    # Versioning
    current_version_no = models.PositiveIntegerField(default=1)
    is_empty = models.BooleanField(default=False)

    # Optional metadata
    canonical_url = models.URLField(blank=True, null=True)
    excerpt = models.TextField(blank=True)
    reading_time = models.PositiveIntegerField(null=True, blank=True)
    addressed_to = models.CharField(
        max_length=32,
        choices=AddressedTo.choices,
        default=AddressedTo.PUBLIC,
        db_index=True,
    )
    enable_outline = models.BooleanField(
        default=False,
        help_text="Opt-in: enable Dispatch outline/section navigator for this piece",
    )

    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True)

    # Group pinning (rank optional for manual order)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_rank = models.IntegerField(null=True, blank=True)

    # Discussion & lightweight analytics
    allow_comments = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)  # denormalized

    # Manager
    objects = WritingPieceManager()

    class Meta(BaseContent.Meta):
        ordering = ["-pinned_at", "-published_at", "-updated_at"]
        indexes = [
            models.Index(fields=["writing_kind"]),
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["scheduled_for"]),
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "pinned_at"]),
            models.Index(fields=["pinned_at"]),
        ]
        constraints = [
            CheckConstraint(
                name="published_requires_published_at",
                check=Q(status="published", published_at__isnull=False) | ~Q(status="published"),
            ),
            CheckConstraint(
                name="scheduled_requires_scheduled_for",
                check=Q(status="scheduled", scheduled_for__isnull=False) | ~Q(status="scheduled"),
            ),
        ]

    # -------- Convenience --------
    @property
    def is_draft(self): return self.status == "draft"

    @property
    def is_published(self): return self.status == "published"

    @property
    def is_announcement(self): return self.writing_kind == "announcement"

    @property
    def is_canonical_kind(self):  # kinds likely to be “living” docs
        return self.writing_kind in ["dispatch", "page", "article"]

    @property
    def current_version(self):
        if self.is_published:
            return self.get_current_artifact()
        return None

    @property
    def group(self):
        # If sponsored by a Group, return the sponsor_object
        if self.sponsor_content_type and self.sponsor_content_type.model == "group":
            return self.sponsor_object
        return None

    # -------- Artifact Resolution (for Publishing) --------

    def get_current_artifact(self):
        """
        Get the latest published version (artifact).
        Used by ContentPlacement to resolve follow_updates=True.
        """
        return self.versions.filter(kind='release').order_by('-sequence_no').first()

    def get_artifact(self, ref):
        """
        Get specific artifact by sequence number or ID.

        Args:
            ref: int (sequence_no) or UUID (artifact id)

        Returns:
            WritingVersion instance or None
        """
        if isinstance(ref, int):
            return self.versions.get(sequence_no=ref)
        return self.versions.get(id=ref)

    # -------- Lifecycle --------

    def publish(self, scheduled_for=None):
        """
        Publish now or mark as scheduled. Ensures a real title and a final slug.
        Slug handling is done in save() method.
        """
        with transaction.atomic():
            # Require a non-empty title for scheduled/published
            if not (self.title or "").strip():
                raise ValidationError("Please add a title before publishing.")

            if scheduled_for:
                self.status = "scheduled"
                self.scheduled_for = scheduled_for
                self.save(update_fields=["status", "scheduled_for", "slug", "updated_at"])
                return self

            # Immediate publish
            self.status = "published"
            self.published_at = timezone.now()
            self.save(update_fields=["status", "published_at", "slug", "updated_at"])

            if not self.versions.exists():
                self.create_version(content_changed=True)

            return self

    def unpublish(self):
        self.status = "draft"
        self.published_at = None
        self.save(update_fields=["status", "published_at", "updated_at"])

    def archive(self):
        self.status = "archived"
        self.save(update_fields=["status", "updated_at"])

    def pin(self, rank: int | None = None):
        self.pinned_at = timezone.now()
        self.pinned_rank = rank
        self.save(update_fields=["pinned_at", "pinned_rank", "updated_at"])

    def unpin(self):
        self.pinned_at = None
        self.pinned_rank = None
        self.save(update_fields=["pinned_at", "pinned_rank", "updated_at"])

    def create_version(self, content_changed=True):
        """Create an immutable snapshot (only when published)."""
        if not self.is_published:
            return None
        with transaction.atomic():
            next_sequence_no = (
                WritingVersion.objects.filter(writing_piece=self)
                .aggregate(Max("sequence_no"))
                .get("sequence_no__max") or 0
            ) + 1
            return WritingVersion.objects.create(
                writing_piece=self,
                sequence_no=next_sequence_no,
                version_label=str(next_sequence_no),
                body_json=self.body_json,
                title=self.title,
                excerpt=self.excerpt,
                kind='release',
                created_by=self.author,
            )

    def increment_view_count(self):
        WritingPiece.objects.filter(id=self.id).update(
            view_count=models.F("view_count") + 1
        )

    def save(self, *args, **kwargs):
        # Clear provisional slug when we have a real title (any status)
        # This centralizes slug handling - publish() no longer needs to do it separately
        if (self.title or "").strip() and is_provisional_slug(self.slug):
            self.slug = None  # triggers BaseContent slug generation

        # Auto-manage is_empty flag based on content
        # A piece is empty if it has no body_json content or only whitespace
        if not self.body_json:
            self.is_empty = True
        else:
            # Check if body_json has actual content (not just empty structure)
            # TipTap typically creates: {"type": "doc", "content": [{"type": "paragraph"}]}
            content = self.body_json.get("content", [])
            has_content = False

            for node in content:
                # Check if any node has text content
                if node.get("content"):
                    # Has nested content - check for actual text
                    for child in node.get("content", []):
                        if child.get("type") == "text" and (child.get("text") or "").strip():
                            has_content = True
                            break
                elif node.get("type") not in ["paragraph", "doc"]:
                    # Has non-paragraph content (images, etc.)
                    has_content = True
                    break

                if has_content:
                    break

            self.is_empty = not has_content

        # Reading time
        if self.body_json:
            wc = count_words_in_prosemirror(self.body_json)
            self.reading_time = (
                max(1, round(wc / 200)) if wc > 0 else 0  # ✅ Direct calculation
            )

        super().save(*args, **kwargs)

    def __str__(self):
        prefix = f"[{self.status.upper()}] " if self.is_draft else ""
        return f"{prefix}{self.get_writing_kind_display()}: {self.title or 'Untitled'}"


class WorkingDocument(BaseModel):
    """
    Mutable draft state for a WritingPiece.
    Supports composable workflow layers (dispatch, review, approval).

    This is the editing layer - all unpublished content lives here.
    When published, content is copied to WritingPiece.body_json.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    # Link to canonical piece
    piece = models.ForeignKey(
        "WritingPiece",
        related_name="working_copies",
        on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text="The user editing this draft"
    )

    # Draft content (solo editing)
    body_json = models.JSONField(default=dict)
    title = models.CharField(max_length=255, blank=True)
    excerpt = models.TextField(blank=True)

    # Autosave tracking
    last_saved_at = models.DateTimeField(auto_now=True)
    auto_save_count = models.PositiveIntegerField(default=0)
    client_session_id = models.CharField(max_length=64, blank=True)

    # === Composable Workflow Layers (Decorator Pattern) ===

    # Collaborative Editing Layer
    dispatch_content = models.ForeignKey(
        'dispatch.DispatchContent',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="working_documents",
        help_text="If set, this draft uses Yjs collaborative editing"
    )

    # Future: Review Layer
    # review_doc = models.ForeignKey(
    #     'review.ReviewDocument',
    #     null=True,
    #     blank=True,
    #     on_delete=models.SET_NULL,
    #     related_name="working_documents",
    #     help_text="If set, this draft is under formal review"
    # )

    # Future: Approval Layer
    # approval_doc = models.ForeignKey(
    #     'approval.ApprovalDocument',
    #     null=True,
    #     blank=True,
    #     on_delete=models.SET_NULL,
    #     related_name="working_documents",
    #     help_text="If set, this draft is awaiting approval"
    # )

    class Meta(BaseModel.Meta):
        unique_together = [("piece", "user")]
        indexes = [
            models.Index(fields=["piece", "user"]),
            models.Index(fields=["last_saved_at"]),
        ]
        verbose_name = "Working Document"
        verbose_name_plural = "Working Documents"

    # === Helper Properties ===

    @property
    def is_collaborative(self):
        """Check if this draft is in collaborative editing mode"""
        return self.dispatch_content is not None

    # Future workflow state helpers:
    # @property
    # def is_in_review(self):
    #     return self.review_doc is not None
    #
    # @property
    # def is_awaiting_approval(self):
    #     return self.approval_doc is not None

    @property
    def workflow_states(self):
        """Return list of active workflow states"""
        states = []
        if self.is_collaborative:
            states.append('collaborative')
        # if self.is_in_review:
        #     states.append('review')
        # if self.is_awaiting_approval:
        #     states.append('approval')
        return states

    def apply_to_piece(self, piece) -> bool:
        """
        Merge this working copy into the canonical piece.
        Returns True if content changed.
        """
        changed_fields = []
        if self.title and self.title != piece.title:
            piece.title = self.title
            changed_fields.append("title")

        if self.excerpt and self.excerpt != piece.excerpt:
            piece.excerpt = self.excerpt
            changed_fields.append("excerpt")

        if self.body_json and self.body_json != piece.body_json:
            piece.body_json = self.body_json
            changed_fields.append("body_json")

        if changed_fields:
            # You might recalc reading time here
            piece.save(update_fields=changed_fields + ["updated_at"])
            return True
        return False


class WritingVersion(BaseVersion):
    """
    Immutable snapshot of a WritingPiece at publication time.
    Inherits from BaseVersion for universal publishing architecture.

    BaseVersion provides: id, created_at, created_by, kind, label, note, content_hash
    """
    writing_piece = models.ForeignKey(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name="versions"
    )

    sequence_no = models.PositiveIntegerField()
    version_label = models.CharField(max_length=32, blank=True, default="")

    # Canonical published content
    body_json = models.JSONField(help_text="Immutable snapshot of published content")
    title = models.CharField(max_length=255)
    excerpt = models.TextField(blank=True)

    # Optional: changelog/notes (in addition to BaseVersion.note)
    changelog = models.TextField(blank=True)

    class Meta(BaseVersion.Meta):
        unique_together = ["writing_piece", "sequence_no"]
        ordering = ["-sequence_no"]
        indexes = [
            models.Index(fields=["writing_piece", "sequence_no"]),
        ]
        verbose_name = "Writing Version"
        verbose_name_plural = "Writing Versions"

    def __str__(self):
        label = self.version_label or self.sequence_no
        return f"{self.writing_piece.title} v{label}"


# WritingPlacement has been replaced by universal ContentPlacement
# See app.publishing.models.ContentPlacement


class WritingComment(BaseModel):
    piece = models.ForeignKey(WritingPiece, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    is_approved = models.BooleanField(default=True)
    is_flagged = models.BooleanField(default=False)  # Keep for moderation

    class Meta:
        ordering = ["created_at"]


class CommentLike(BaseModel):
    """Track comment likes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(
        WritingComment,
        on_delete=models.CASCADE,
        related_name="likes"  # Enables comment.likes.count() in serializers
    )

    class Meta:
        unique_together = ["user", "comment"]


class Seed(BaseModel):
    """
    Lowest-friction capture. Plain text only (v1), autosaves, can be promoted to WorkingCopy later.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seeds"
    )
    body_text = models.TextField(blank=True, default="")  # plaintext only (v1)

    SEED_KIND_CHOICES = [
        ("text", "Text"),
        ("voice", "Voice"),
    ]
    SEED_STATUS_CHOICES = [
        ("ready", "Ready"),
        ("processing", "Processing"),
        ("failed", "Failed"),
    ]
    kind = models.CharField(max_length=16, choices=SEED_KIND_CHOICES, default="text")
    status = models.CharField(max_length=16, choices=SEED_STATUS_CHOICES, default="ready")

    audio_file = models.ForeignKey(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voice_seeds",
    )

    transcript_text = models.TextField(blank=True, null=True)
    transcript_hash = models.CharField(max_length=64, blank=True, null=True)
    transcript_created_at = models.DateTimeField(blank=True, null=True)
    transcript_error = models.TextField(blank=True, null=True)
    transcript_provider = models.CharField(max_length=32, blank=True, null=True)
    transcript_model = models.CharField(max_length=64, blank=True, null=True)
    transcript_backend = models.CharField(max_length=32, blank=True, null=True)
    body_hash = models.CharField(max_length=64, blank=True, null=True)
    edited_after_transcription = models.BooleanField(default=False)

    # Future-facing, safe to keep nullable
    promoted_to = models.OneToOneField(
        "writing.WorkingDocument",  # Updated to new model name
        null=True, blank=True, on_delete=models.SET_NULL, related_name="seed_origin"
    )
    context_url = models.URLField(blank=True, null=True)  # optional, set by share/ingest
    source = models.CharField(max_length=64, blank=True, null=True)  # "web","android","ios","share_target", etc.

    class Meta(BaseModel.Meta):
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["author", "updated_at"]),
        ]

    def __str__(self):
        return f"Seed<{self.id}> by {self.author_id}"





# Type-specific fields (OneToOne when needed)

class ArticleFields(models.Model):
    """Extra fields for Article writing kind"""
    piece = models.OneToOneField(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name="article_fields"
    )

    cover_image = models.ImageField(upload_to="articles/covers/", null=True, blank=True)
    hero_image = models.ImageField(upload_to="articles/heroes/", null=True, blank=True)
    toc_enabled = models.BooleanField(default=True)
    layout_style = models.CharField(
        max_length=20,
        choices=[
            ("standard", "Standard"),
            ("feature", "Feature"),
            ("minimal", "Minimal"),
        ],
        default="standard"
    )
    series_id = models.UUIDField(null=True, blank=True)


class AnnouncementFields(models.Model):
    """Extra fields for Newsletter/Lantern writing kind"""
    piece = models.OneToOneField(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name="announcement_fields"
    )

    subject_line = models.CharField(max_length=255)
    list_id = models.CharField(max_length=100, null=True, blank=True)  # Support external system IDs
    campaign_id = models.CharField(max_length=100, null=True, blank=True)
    send_state = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("sending", "Sending"),
            ("sent", "Sent"),
            ("failed", "Failed"),
        ],
        default="draft"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    open_rate = models.FloatField(null=True, blank=True)
    click_rate = models.FloatField(null=True, blank=True)




class DispatchFields(models.Model):
    """Extra fields for Dispatch collaborative docs"""
    piece = models.OneToOneField(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name="dispatch_fields"
    )

    doc_uuid = models.UUIDField(unique=True)
    folder_path = models.CharField(max_length=500, blank=True)
    is_primary_source = models.BooleanField(
        default=True,
        help_text="Is this the main doc, or a placement/excerpt?"
    )
    collaboration_enabled = models.BooleanField(default=True)




# QuerySets and Managers for common operations
class WritingPieceQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status="published")

    def by_sponsor(self, obj):
        ct = ContentType.objects.get_for_model(obj)
        return self.filter(sponsor_content_type=ct, sponsor_object_id=str(obj.pk))

    def by_kind(self, kind):
        return self.filter(writing_kind=kind)

    def canonical_kinds(self):
        return self.filter(writing_kind__in=["dispatch", "page", "article"])


# Add the custom manager to WritingPiece
WritingPiece.add_to_class("objects", WritingPieceQuerySet.as_manager())


class ImportReceipt(BaseModel):
    """
    Tracks provenance and idempotency for imported documents.
    Stores all import metadata so WritingPiece stays clean.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(
        max_length=32,
        default="docx",
        help_text="Import source format: docx, md, etc.",
    )
    source_sha256 = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 hash of the source file for idempotency",
    )
    original_filename = models.CharField(max_length=512)
    source_url = models.URLField(
        blank=True,
        null=True,
        help_text="Original document URL (e.g. Google Docs link)",
    )
    created_writing_piece = models.ForeignKey(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name="import_receipts",
    )
    imported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    import_notes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extracted comments, warnings, stats from import",
    )

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["source_sha256"]),
            models.Index(fields=["source_type"]),
        ]

    def __str__(self):
        return f"ImportReceipt<{self.source_type}:{self.original_filename}>"


# ============================================================================
# Leaf — Storyline content unit
# ============================================================================

class Leaf(BaseModel):
    """
    First-class Storyline content unit.
    Sits between Seed (private capture) and WritingPiece (structured publication).

    Two kinds (one model):
    - Native Leaf: original content written for Storyline
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


# ============================================================================
# LeafComment — Comments on Leaves (Leaf is the social node)
# ============================================================================

class LeafComment(BaseModel):
    """
    Comments on Leaves. One-level threading only.
    Leaf-only for v1 — WritingPiece discussion is a separate future surface.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leaf_comments"
    )
    leaf = models.ForeignKey(
        Leaf, on_delete=models.CASCADE, related_name="comments",
    )
    content = models.TextField()
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="replies",
    )
    is_approved = models.BooleanField(default=True)
    is_flagged = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        ordering = ["created_at"]

    def clean(self):
        if self.parent and self.parent.parent_id is not None:
            raise ValidationError("Only one level of threading is allowed.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"LeafComment<{self.id}> on Leaf<{self.leaf_id}>"


# ============================================================================
# Backwards Compatibility Alias
# ============================================================================

# Alias for backwards compatibility with existing code
WritingWorkingCopy = WorkingDocument
