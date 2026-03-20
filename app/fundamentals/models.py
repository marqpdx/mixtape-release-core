# fundamentals/models.py

# ============================================================================
# BaseData and BaseContent: Core abstract models with polymorphic sponsorship
# ============================================================================

import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from .bases import BaseModel


User = get_user_model()

# Slug generation constants
MAX_SLUG_ATTEMPTS = 100


def default_slug():
    """
    Generate a placeholder slug for content that hasn't been given a slug yet.
    Pattern: 'untitled---{random}'
    """
    return f"untitled---{get_random_string(8)}"


def is_provisional_slug(slug: str) -> bool:
    """
    Check if a slug is a placeholder that should be auto-regenerated.
    Returns True if slug starts with 'untitled---' or 'temp-'.
    """
    return slug.startswith("untitled---") or slug.startswith("temp-")


class BaseData(BaseModel):
    """
    Shared content base with polymorphic sponsorship and slug lifecycle.
    - Slug defaults to a placeholder: 'untitled---<random>'
    - If the slug is a placeholder AND title becomes non-empty, we auto-regenerate to a title-based slug.
    - If/when you allow manual slug editing, flip slug_is_custom=True to freeze it.
    """

    summary = models.TextField(blank=True, default="")
    title = models.CharField(max_length=100, blank=True, default="")

    # Slug lifecycle
    slug = models.SlugField(
        max_length=64,
        unique=False,  # Uniqueness enforced by subclasses (global for Tag, sponsor-scoped for BaseContent/Category)
        default=default_slug,   # ✅ prevents migration prompt, always non-null
        editable=False,
    )
    slug_is_custom = models.BooleanField(
        default=False,
        help_text="If True, the slug will not auto-regenerate from title."
    )
    slug_history = models.JSONField(
        blank=True,
        default=list,
        help_text="Previous slugs for optional redirects (leave empty for now)."
    )

    class Meta:
        abstract = True
        ordering = ("-updated_at",)

    def slug_exists(self, slug: str) -> bool:
        """
        Check for duplicate slugs within this model.
        Subclasses can override for cross-model uniqueness.
        """
        return self.__class__.objects.filter(slug=slug).exclude(pk=self.pk).exists()

    def _build_unique_slug(self, base: str) -> str:
        """
        Generate a unique slug by appending a counter if needed.
        """
        slug = base
        counter = 2
        while self.slug_exists(slug):
            if counter > MAX_SLUG_ATTEMPTS:
                raise ValueError(f"Too many duplicate slugs for base '{base}'")
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def save(self, *args, **kwargs):
        """
        Slug rules:
        - On first save, slug is guaranteed (default_slug).
        - If slug is a placeholder AND title is non-empty, regenerate slug from title.
        - If slug_is_custom=True, never auto-regenerate (future manual edit mode).
        """
        title_str = (self.title or "").strip()

        # Ensure slug exists (should already from default)
        if not self.slug:
            # fall back just in case
            self.slug = default_slug()

        # auto-regenerate if we still have a placeholder AND a real title now,
        # and slug has not been manually customized.
        if not self.slug_is_custom and is_provisional_slug(self.slug) and title_str:
            base = slugify(title_str)
            if base:
                new_slug = self._build_unique_slug(base)
                if new_slug != self.slug:
                    # track old slug (for possible redirects later)
                    if self.slug and self.slug not in self.slug_history:
                        self.slug_history.append(self.slug)
                    self.slug = new_slug

        super().save(*args, **kwargs)


class BaseClassification(BaseData):
    """
    Base class for classification systems (Tags, Categories, etc.)

    Inherits from BaseData to get:
    - title (the tag/category name)
    - slug (for URLs)
    - summary (optional description)
    """

    # Count of times this classification is used
    usage_count = models.PositiveIntegerField(
        default=0,
        help_text="Cached count of how many items use this classification"
    )

    # Optional color/styling
    color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="Hex color code for display (e.g., #FF5733)"
    )

    class Meta(BaseData.Meta):
        abstract = True
        ordering = ['title']  # Alphabetical by default

    def __str__(self):
        return self.title or "Unnamed"

    def increment_usage(self):
        """Increment usage count (called when attached to content)"""
        self.usage_count = models.F('usage_count') + 1
        self.save(update_fields=['usage_count'])

    def decrement_usage(self):
        """Decrement usage count (called when detached from content)"""
        self.usage_count = models.F('usage_count') - 1
        self.save(update_fields=['usage_count'])


class BaseContent(BaseData):
    """
    Extended content base with polymorphic sponsorship, authorship, and classifications.
    - sponsor: Generic FK to any model (User, Group, etc.) that sponsors this content
    - author: Optional User who authored the content
    - submitted_by: User who submitted/created the record
    - tags/categories: Generic relations to ClassificationUsage
    - attachments: Generic relation to AssetUsage
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_%(class)ss"
    )

    # Polymorphic sponsor (User, Group, etc.)
    sponsor_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    # Author (may differ from sponsor)
    author = models.ForeignKey(
        User,
        related_name="authored_%(class)ss",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    author_name = models.CharField(max_length=255, blank=True, default="")

    body = models.TextField(blank=True, default="")

    # Generic relations to classification and asset systems
    tags = GenericRelation(
        'classifications.ClassificationUsage',
        content_type_field="classification_client_content_type",
        object_id_field="classification_client_object_id",
        related_query_name="%(app_label)s_%(class)s_tags",
        blank=True
    )

    categories = GenericRelation(
        'classifications.ClassificationUsage',
        content_type_field="classification_client_content_type",
        object_id_field="classification_client_object_id",
        related_query_name="%(app_label)s_%(class)s_categories",
        blank=True
    )

    # attachments = GenericRelation('assets.AssetUsage', blank=True)  # TODO: Uncomment when assets app is ready

    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [
            # Sponsor-scoped slug uniqueness
            models.UniqueConstraint(
                fields=['sponsor_content_type', 'sponsor_object_id', 'slug'],
                name='%(app_label)s_%(class)s_slug_sponsor_unique'
            )
        ]
        indexes = [
            models.Index(fields=["sponsor_content_type", "sponsor_object_id"]),
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "slug"]),
            models.Index(fields=["author", "-created_at"]),
            models.Index(fields=["submitted_by", "-created_at"]),
        ]

    # ---- Properties ----

    @property
    def sponsor_type(self):
        """Return the model name of the sponsor (e.g., 'user', 'group')"""
        return self.sponsor_content_type.model

    @property
    def sponsor_id(self):
        """Return the UUID of the sponsor object"""
        return self.sponsor_object_id

    @property
    def sponsor_display(self):
        """Return a display-friendly name for the sponsor"""
        return getattr(self.sponsor, "display_name", str(self.sponsor))

    @property
    def author_display(self):
        """Return a display-friendly name for the author"""
        if self.author_name:
            return self.author_name
        return getattr(self.author, "display_name", str(self.author)) if self.author else "Unknown"

    @property
    def is_self_created(self):
        """Check if the author is the same as the sponsor (for User sponsors)"""
        return self.author == self.sponsor if isinstance(self.sponsor, User) else False

    # ---- Methods ----

    def slug_exists(self, slug: str) -> bool:
        """
        Override BaseData.slug_exists() to check sponsor-scoped uniqueness.

        Checks if a slug already exists for content with the same sponsor.
        This allows different sponsors to use the same slug.
        """
        # Safety check: sponsor must be set before we can check uniqueness
        if not hasattr(self, 'sponsor_content_type') or not self.sponsor_object_id:
            # During initialization, before sponsor is set
            return False

        return self.__class__.objects.filter(
            sponsor_content_type=self.sponsor_content_type,
            sponsor_object_id=self.sponsor_object_id,
            slug=slug
        ).exclude(pk=self.pk).exists()

    def set_sponsor(self, sponsor):
        """Set the polymorphic sponsor for this content"""
        self.sponsor_content_type = ContentType.objects.get_for_model(sponsor)
        self.sponsor_object_id = str(sponsor.pk)

    def set_submitted_by(self, user):
        """Set the user who submitted this content"""
        self.submitted_by = user

    def add_classification(self, classification, **kwargs):
        """
        Add a tag or category to this content.
        Returns the ClassificationUsage instance.
        """
        from classifications.models import ClassificationUsage

        content_content_type = ContentType.objects.get_for_model(self)
        classification_content_type = ContentType.objects.get_for_model(classification)

        classification_inuse, created = ClassificationUsage.objects.update_or_create(
            classification_client_object_id=self.pk,
            classification_client_content_type=content_content_type,
            classification_object_id=classification.pk,
            classification_content_type=classification_content_type,
            defaults=kwargs
        )

        # Update usage count if newly created
        if created:
            classification.increment_usage()

        return classification_inuse

    def remove_classification(self, classification):
        """
        Remove a tag or category from this content.
        """
        from classifications.models import ClassificationUsage

        content_content_type = ContentType.objects.get_for_model(self)
        classification_content_type = ContentType.objects.get_for_model(classification)

        deleted_count, _ = ClassificationUsage.objects.filter(
            classification_client_object_id=self.pk,
            classification_client_content_type=content_content_type,
            classification_object_id=classification.pk,
            classification_content_type=classification_content_type,
        ).delete()

        # Update usage count if something was deleted
        if deleted_count > 0:
            classification.decrement_usage()

        return deleted_count > 0


class LayoutParent(models.Model):
    """
    Minimal abstract base for models that can have layouts
    Phase 2: Placeholder for Groups
    Phase 4+: Will add actual layout functionality
    """
    class Meta:
        abstract = True


# ============================================================================
# NOTES ON USAGE
# ============================================================================
# - BaseData: Use for simple content that needs slug lifecycle but not full sponsorship
# - BaseContent: Use for full-featured content with sponsors, authors
# - The sponsor pattern allows any model to sponsor content (User, Group, Organization, etc.)
# - Tags/categories/attachments are commented out until those apps are ready
# ============================================================================

# ============================================================================
# Follow — User-to-user follow relationships (for Streams)
# ============================================================================

class Follow(BaseModel):
    """
    Explicit user-to-user follow. Streams query = Leaves from followed users.
    No algorithmic suggestions — pure chronological from explicit follows.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    follower = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="following",
        help_text="The user who follows",
    )
    following = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="followers",
        help_text="The user being followed",
    )

    class Meta(BaseModel.Meta):
        unique_together = [("follower", "following")]
        indexes = [
            models.Index(fields=["follower", "created_at"]),
            models.Index(fields=["following", "created_at"]),
        ]

    def clean(self):
        if self.follower_id == self.following_id:
            from django.core.exceptions import ValidationError
            raise ValidationError("Cannot follow yourself.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Follow: {self.follower_id} → {self.following_id}"


# ============================================================================
# Phase 4 Workbench Authoring Models
# ============================================================================
from .models_milldraft import (
    MillDraft,
    MillDraftStatus,
    ContentProfileConfig,
    PublishSafetyClass,
    FieldRiskClass,
    ValidationSeverity,
    ReviewQueueEntry,
    ReviewQueueDecision,
    MillDraftSuggestion,
    SuggestionSource,
)
