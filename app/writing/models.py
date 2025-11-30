# models/writing.py

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, CheckConstraint
from django.db import models
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid

from mixtape.constants import PROVISIONAL_SLUG_PREFIX
from fundamentals.models import BaseContent
from fundamentals.bases import BaseModel
from utils.writing.writing_utils import count_words_in_prosemirror
from writing.choices import ContentStatus

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
    def drafts(self): return self.filter(status='draft')
    def published(self): return self.filter(status='published')
    def scheduled(self): return self.filter(status='scheduled')
    def announcements(self): return self.filter(writing_kind='announcement')
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
            ('post', 'Post'),
            ('article', 'Article'),
            ('dispatch', 'Dispatch'),
            ('forum', 'Forum Post'),
            ('announcement', 'Announcement'),
            ('almanac', 'Almanac'),
            ('page', 'Page'),
            ('other', 'Other'),
        ],
        default='post',
    )

    # Versioning
    current_version_no = models.PositiveIntegerField(default=1)
    is_empty = models.BooleanField(default=False)

    # Optional metadata
    canonical_url = models.URLField(blank=True, null=True)
    excerpt = models.TextField(blank=True)
    reading_time = models.PositiveIntegerField(null=True, blank=True)

    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True)

    # Group pinning (rank optional for manual order)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_rank = models.IntegerField(null=True, blank=True)

    # Discussion & lightweight analytics
    allow_comments = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)  # denormalized

    status = models.CharField(
        max_length=20,
        choices=ContentStatus.choices,
        default=ContentStatus.DRAFT,
        db_index=True,
    )

    # Manager
    objects = WritingPieceManager()

    class Meta(BaseContent.Meta):
        ordering = ['-pinned_at', '-published_at', '-updated_at']
        indexes = [
            models.Index(fields=['writing_kind']),
            models.Index(fields=['status', 'published_at']),
            models.Index(fields=['scheduled_for']),
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id', 'pinned_at']),
            models.Index(fields=['pinned_at']),
        ]
        constraints = [
            CheckConstraint(
                name='published_requires_published_at',
                check=Q(status='published', published_at__isnull=False) | ~Q(status='published'),
            ),
            CheckConstraint(
                name='scheduled_requires_scheduled_for',
                check=Q(status='scheduled', scheduled_for__isnull=False) | ~Q(status='scheduled'),
            ),
        ]

    # -------- Convenience --------
    @property
    def is_draft(self): return self.status == 'draft'

    @property
    def is_published(self): return self.status == 'published'

    @property
    def is_announcement(self): return self.writing_kind == 'announcement'

    @property
    def is_canonical_kind(self):  # kinds likely to be “living” docs
        return self.writing_kind in ['dispatch', 'page', 'article']

    @property
    def current_version(self):
        if self.is_published:
            return self.versions.filter(version_no=self.current_version_no).first()
        return None

    @property
    def group(self):
        # If sponsored by a Group, return the sponsor_object
        if self.sponsor_content_type and self.sponsor_content_type.model == 'group':
            return self.sponsor_object
        return None

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
        self.status = 'draft'
        self.published_at = None
        self.save(update_fields=['status', 'published_at', 'updated_at'])

    def archive(self):
        self.status = 'archived'
        self.save(update_fields=['status', 'updated_at'])

    def pin(self, rank: int | None = None):
        self.pinned_at = timezone.now()
        self.pinned_rank = rank
        self.save(update_fields=['pinned_at', 'pinned_rank', 'updated_at'])

    def unpin(self):
        self.pinned_at = None
        self.pinned_rank = None
        self.save(update_fields=['pinned_at', 'pinned_rank', 'updated_at'])

    def create_version(self, content_changed=True):
        """Create an immutable snapshot (only when published)."""
        if not self.is_published:
            return None
        with transaction.atomic():
            if content_changed:
                self.current_version_no += 1
                self.save(update_fields=["current_version_no", "updated_at"])
            return WritingVersion.objects.create(
                piece=self,
                version_no=self.current_version_no,
                body_json=self.body_json,
                title=self.title,
                excerpt=self.excerpt,
            )

    def increment_view_count(self):
        WritingPiece.objects.filter(id=self.id).update(
            view_count=models.F('view_count') + 1
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
            content = self.body_json.get('content', [])
            has_content = False

            for node in content:
                # Check if any node has text content
                if node.get('content'):
                    # Has nested content - check for actual text
                    for child in node.get('content', []):
                        if child.get('type') == 'text' and (child.get('text') or '').strip():
                            has_content = True
                            break
                elif node.get('type') not in ['paragraph', 'doc']:
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


class WritingWorkingCopy(models.Model):
    """
    Per-user autosave buffer for a WritingPiece.
    Keeps keystroke-level writes off the canonical row.
    """
    piece = models.ForeignKey('WritingPiece', related_name='working_copies', on_delete=models.CASCADE)
    user  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    body_json = models.JSONField(default=dict)
    title     = models.CharField(max_length=255, blank=True)
    excerpt   = models.TextField(blank=True)

    last_saved_at   = models.DateTimeField(auto_now=True)
    auto_save_count = models.PositiveIntegerField(default=0)
    client_session_id = models.CharField(max_length=64, blank=True)

    class Meta:
        unique_together = [('piece', 'user')]
        indexes = [
            models.Index(fields=['piece', 'user']),
            models.Index(fields=['last_saved_at']),
        ]

    def apply_to_piece(self, piece) -> bool:
        """
        Merge this working copy into the canonical piece.
        Returns True if content changed.
        """
        changed_fields = []
        if self.title and self.title != piece.title:
            piece.title = self.title
            changed_fields.append('title')

        if self.excerpt and self.excerpt != piece.excerpt:
            piece.excerpt = self.excerpt
            changed_fields.append('excerpt')

        if self.body_json and self.body_json != piece.body_json:
            piece.body_json = self.body_json
            changed_fields.append('body_json')

        if changed_fields:
            # You might recalc reading time here
            piece.save(update_fields=changed_fields + ['updated_at'])
            return True
        return False


class WritingVersion(models.Model):
    """
    Immutable snapshots of WritingPiece content.
    Created on publish + explicit versioning.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    piece = models.ForeignKey(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name='versions'
    )

    version_no = models.PositiveIntegerField()

    # Snapshot of content at this version
    body_json = models.JSONField()
    title = models.CharField(max_length=255)
    excerpt = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # Optional: changelog/notes
    changelog = models.TextField(blank=True)

    class Meta:
        ordering = ['-version_no']
        unique_together = ['piece', 'version_no']
        indexes = [
            models.Index(fields=['piece', 'version_no']),
        ]

    def __str__(self):
        return f"{self.piece.title} v{self.version_no}"


class WritingPlacement(BaseModel):
    """
    Distribution routing - where a piece gets published.
    Links WritingPiece to destination with behavior settings.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    piece = models.ForeignKey(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name='placements'
    )

    # Polymorphic destination (User, Group, LanternList, ForumThread, etc.)
    target_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_object_id = models.UUIDField()
    target = GenericForeignKey('target_content_type', 'target_object_id')

    # Channel context
    channel = models.CharField(
        max_length=20,
        choices=[
            ('feed', 'Feed'),
            ('lantern', 'Newsletter'),
            ('forum', 'Forum'),
            ('dispatch', 'Dispatch'),
            ('almanac', 'Almanac'),
            ('page', 'Page'),
        ]
    )

    # Version behavior
    follow_updates = models.BooleanField(
        default=True,
        help_text="If True, shows current version. If False, locked to specific version."
    )
    locked_version_no = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Version to display when follow_updates=False"
    )

    # Presentation options
    visibility = models.CharField(
        max_length=20,
        choices=[
            ('public', 'Public'),
            ('members', 'Members Only'),
            ('private', 'Private'),
            ('scheduled', 'Scheduled'),
        ],
        default='public'
    )

    is_excerpt = models.BooleanField(
        default=False,
        help_text="Show excerpt vs full content"
    )

    # Advanced: partial publishing (future) - document expected schema
    fragment_selector = models.JSONField(
        null=True, blank=True,
        help_text="""JSON selector for partial content. Expected schemas:
        - {type: "blocks", ids: ["block-uuid-1", "block-uuid-2"]}
        - {type: "headingRange", from: {level: 2, text: "Introduction"}, to: {level: 2, text: "Conclusion"}}
        """
    )

    # Per-placement overrides - document expected keys
    overrides = models.JSONField(
        null=True, blank=True,
        help_text="""JSON overrides for this placement. Expected keys:
        - title_override: custom title
        - excerpt_override: custom excerpt
        - cover_override: custom cover image URL
        - lantern_subject: newsletter subject line override
        """
    )

    # Placement metadata
    placed_at = models.DateTimeField(auto_now_add=True)
    order = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)

    @property
    def effective_version_no(self):
        """Returns version number to display for this placement"""
        if self.follow_updates:
            return self.piece.current_version_no
        return self.locked_version_no or 1

    def get_content_for_display(self):
        """Returns content to display for this placement"""
        if self.follow_updates:
            content = self.piece.body_json
            title = self.piece.title
            excerpt = self.piece.excerpt
        else:
            version = self.piece.versions.get(version_no=self.locked_version_no)
            content = version.body_json
            title = version.title
            excerpt = version.excerpt

        # Apply per-placement overrides
        if self.overrides:
            title = self.overrides.get('title_override', title)
            excerpt = self.overrides.get('excerpt_override', excerpt)

        return {
            'title': title,
            'excerpt': excerpt,
            'body_json': content,
            'is_excerpt': self.is_excerpt,
        }

    def clean(self):
        """Model validation to catch errors early"""
        from django.core.exceptions import ValidationError

        # Ensure locked_version_no is present when follow_updates=False
        if not self.follow_updates and not self.locked_version_no:
            raise ValidationError("locked_version_no is required when follow_updates is False.")

        # Ensure version exists when locking
        if self.locked_version_no and hasattr(self, 'piece') and self.piece:
            if not self.piece.versions.filter(version_no=self.locked_version_no).exists():
                raise ValidationError(f"Version {self.locked_version_no} does not exist for this piece.")

    class Meta:
        ordering = ['-placed_at']
        # Prevent duplicate placements to same target
        unique_together = ['piece', 'target_content_type', 'target_object_id', 'channel']
        indexes = [
            models.Index(fields=['channel']),
            models.Index(fields=['target_content_type', 'target_object_id']),
            models.Index(fields=['piece']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(follow_updates=True) | models.Q(locked_version_no__isnull=False),
                name='placement_locked_when_not_following'
            )
        ]

    def __str__(self):
        return f"{self.piece.title} → {self.target} ({self.channel})"


class WritingComment(BaseModel):
    piece = models.ForeignKey(WritingPiece, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    is_approved = models.BooleanField(default=True)
    is_flagged = models.BooleanField(default=False)  # Keep for moderation

    class Meta:
        ordering = ['created_at']


class CommentLike(BaseModel):
    """Track comment likes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(
        WritingComment,
        on_delete=models.CASCADE,
        related_name='likes'  # Enables comment.likes.count() in serializers
    )

    class Meta:
        unique_together = ['user', 'comment']




class Seed(BaseModel):
    """
    Lowest-friction capture. Plain text only (v1), autosaves, can be promoted to WorkingCopy later.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seeds"
    )
    body_text = models.TextField(blank=True, default="")  # plaintext only (v1)

    # Future-facing, safe to keep nullable
    promoted_to = models.OneToOneField(
        "writing.WritingWorkingCopy",  # your existing model
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
        related_name='article_fields'
    )

    cover_image = models.ImageField(upload_to='articles/covers/', null=True, blank=True)
    hero_image = models.ImageField(upload_to='articles/heroes/', null=True, blank=True)
    toc_enabled = models.BooleanField(default=True)
    layout_style = models.CharField(
        max_length=20,
        choices=[
            ('standard', 'Standard'),
            ('feature', 'Feature'),
            ('minimal', 'Minimal'),
        ],
        default='standard'
    )
    series_id = models.UUIDField(null=True, blank=True)


class AnnouncementFields(models.Model):
    """Extra fields for Newsletter/Lantern writing kind"""
    piece = models.OneToOneField(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name='announcement_fields'
    )

    subject_line = models.CharField(max_length=255)
    list_id = models.CharField(max_length=100, null=True, blank=True)  # Support external system IDs
    campaign_id = models.CharField(max_length=100, null=True, blank=True)
    send_state = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('scheduled', 'Scheduled'),
            ('sending', 'Sending'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
        ],
        default='draft'
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    open_rate = models.FloatField(null=True, blank=True)
    click_rate = models.FloatField(null=True, blank=True)


# class ForumFields(models.Model):
#     """Extra fields for Forum writing kind"""
#     piece = models.OneToOneField(
#         WritingPiece,
#         on_delete=models.CASCADE,
#         related_name='forum_fields'
#     )

#     discussion = models.ForeignKey('threadworks.Discussion', on_delete=models.CASCADE)  # FK instead of UUID
#     parent_piece = models.ForeignKey(
#         WritingPiece,
#         null=True, blank=True,
#         on_delete=models.CASCADE,
#         related_name='replies'
#     )
#     depth = models.PositiveIntegerField(default=0)
#     sort_key = models.CharField(max_length=100)
#     is_solution = models.BooleanField(default=False)

#     class Meta:
#         indexes = [
#             models.Index(fields=['discussion', 'sort_key']),
#         ]


class DispatchFields(models.Model):
    """Extra fields for Dispatch collaborative docs"""
    piece = models.OneToOneField(
        WritingPiece,
        on_delete=models.CASCADE,
        related_name='dispatch_fields'
    )

    doc_uuid = models.UUIDField(unique=True)
    folder_path = models.CharField(max_length=500, blank=True)
    is_primary_source = models.BooleanField(
        default=True,
        help_text="Is this the main doc, or a placement/excerpt?"
    )
    collaboration_enabled = models.BooleanField(default=True)


# class AlmanacFields(models.Model):
#     """Extra fields for Almanac event writing"""
#     piece = models.OneToOneField(
#         WritingPiece,
#         on_delete=models.CASCADE,
#         related_name='almanac_fields'
#     )

#     event = models.ForeignKey('almanac.EventSeries', on_delete=models.CASCADE)  # FK instead of UUID
#     phase = models.CharField(
#         max_length=20,
#         choices=[
#             ('pre', 'Pre-Event'),
#             ('during', 'During Event'),
#             ('post', 'Post-Event'),
#         ]
#     )
#     content_type = models.CharField(
#         max_length=20,
#         choices=[
#             ('invite', 'Invitation'),
#             ('runsheet', 'Run of Show'),
#             ('recap', 'Recap'),
#             (            'notes', 'Notes'),
#         ]
#     )


# QuerySets and Managers for common operations
class WritingPieceQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status='published')

    def by_sponsor(self, obj):
        ct = ContentType.objects.get_for_model(obj)
        return self.filter(sponsor_content_type=ct, sponsor_object_id=str(obj.pk))

    def by_kind(self, kind):
        return self.filter(writing_kind=kind)

    def canonical_kinds(self):
        return self.filter(writing_kind__in=['dispatch', 'page', 'article'])


# Add the custom manager to WritingPiece
WritingPiece.add_to_class('objects', WritingPieceQuerySet.as_manager())