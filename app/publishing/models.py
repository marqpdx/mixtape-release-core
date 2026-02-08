# app/publishing/models.py

"""
Universal publishing models for Mixtape.

Architecture:
- BaseVersion: Abstract base for all immutable content artifacts
- PublicationGroup: Groups placements from a single publish action
- ContentPlacement: Universal placement model for all content types
"""

import uuid
from django.db import models
from django.db.models import Q, CheckConstraint
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from fundamentals.bases import BaseModel

User = get_user_model()


# ==============================================================================
# Abstract Base for Artifacts
# ==============================================================================

class BaseVersion(models.Model):
    """
    Abstract base for all immutable content artifacts.
    Provides common snapshot/versioning behavior across all content types.

    All artifact types (WritingVersion, DispatchSnapshot, NewsletterIssue,
    EventSnapshot, etc.) inherit from this base.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_created"
    )

    # Semantic metadata
    kind = models.CharField(
        max_length=50,
        default='snapshot',
        help_text="Semantic type: 'snapshot', 'release', 'issue', 'version'"
    )
    label = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)

    # Optional integrity checking
    content_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        label = self.label or self.kind
        return f"{self.__class__.__name__} ({label}) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


# ==============================================================================
# Publication Group
# ==============================================================================

class PublicationGroup(BaseModel):
    """
    Groups placements created in a single publish action.
    Enables bulk operations, rollback, and audit trail.

    Use cases:
    - Bulk unpublish: pub_group.placements.all().delete()
    - Audit trail: "Show me all times this piece was published"
    - Analytics: "How many channels did we publish to?"
    - Rollback: "Undo this entire publish action"
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='publication_groups'
    )

    # What was published (for reference/audit)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    source_object_id = models.UUIDField()
    source = GenericForeignKey('source_content_type', 'source_object_id')

    # Optional metadata
    note = models.TextField(
        blank=True,
        help_text="e.g., 'v2.0 release', 'hotfix for typo'"
    )

    class Meta(BaseModel.Meta):
        ordering = ['-created_at']
        verbose_name = 'Publication Group'
        verbose_name_plural = 'Publication Groups'

    def __str__(self):
        source_str = str(self.source) if self.source else f"{self.source_content_type} #{self.source_object_id}"
        return f"Publication: {source_str} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


# ==============================================================================
# Content Placement
# ==============================================================================

class ContentPlacement(BaseModel):
    """
    Universal placement model for all content types.
    Represents an intentional distribution decision.

    Resolution order:
    1. If locked_artifact exists → use it
    2. Else if follow_updates=True → source.get_current_artifact()
    3. Else → invalid (prevented by validation)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Publication grouping
    publication_group = models.ForeignKey(
        PublicationGroup,
        related_name='placements',
        on_delete=models.CASCADE
    )
    placed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='content_placements'
    )

    # Source: the root entity being published
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='source_placements'
    )
    source_object_id = models.UUIDField()
    source = GenericForeignKey('source_content_type', 'source_object_id')

    # Target: where it's being placed
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='target_placements'
    )
    target_object_id = models.UUIDField()
    target = GenericForeignKey('target_content_type', 'target_object_id')

    # Channel and visibility
    channel = models.CharField(
        max_length=50,
        choices=[
            ('feed', 'Feed'),
            ('shelf', 'Shelf'),
            ('lantern', 'Newsletter'),
            ('forum', 'Forum'),
            ('dispatch', 'Dispatch'),
            ('almanac', 'Events'),
            ('page', 'Page'),
        ]
    )
    visibility = models.CharField(
        max_length=20,
        choices=[
            ('public', 'Public'),
            ('members', 'Members Only'),
            ('unlisted', 'Unlisted'),
            ('private', 'Private'),
            ('scheduled', 'Scheduled'),
        ]
    )

    # Version behavior
    follow_updates = models.BooleanField(
        default=False,
        help_text="If True, display updates when source creates new artifacts. "
                  "If False, locked to specific artifact."
    )

    # Artifact locking (universal)
    locked_artifact_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='locked_placements',
        null=True,
        blank=True
    )
    locked_artifact_object_id = models.UUIDField(null=True, blank=True)
    locked_artifact = GenericForeignKey(
        'locked_artifact_content_type',
        'locked_artifact_object_id'
    )

    # Display customization
    is_excerpt = models.BooleanField(default=False)
    fragment_selector = models.JSONField(
        null=True,
        blank=True,
        help_text="Future: specify which content fragments to show"
    )
    overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Override title, excerpt, cover, etc. Keys: title, excerpt, subject, cover_image"
    )
    order_index = models.IntegerField(default=0)

    class Meta(BaseModel.Meta):
        ordering = ['-created_at']
        verbose_name = 'Content Placement'
        verbose_name_plural = 'Content Placements'
        indexes = [
            models.Index(fields=['source_content_type', 'source_object_id']),
            models.Index(fields=['target_content_type', 'target_object_id']),
            models.Index(fields=['channel', 'visibility']),
        ]
        constraints = [
            # Prevent duplicate placements
            models.UniqueConstraint(
                fields=['source_content_type', 'source_object_id',
                       'target_content_type', 'target_object_id', 'channel'],
                name='unique_placement'
            ),
            CheckConstraint(
                name='placement_valid_state',
                check=(
                    Q(follow_updates=True) &
                    Q(locked_artifact_content_type__isnull=True) &
                    Q(locked_artifact_object_id__isnull=True)
                ) | (
                    Q(follow_updates=False) &
                    Q(locked_artifact_content_type__isnull=False) &
                    Q(locked_artifact_object_id__isnull=False)
                )
            ),
            CheckConstraint(
                name='placement_lock_fields_both_null_or_set',
                check=(
                    Q(locked_artifact_content_type__isnull=True, locked_artifact_object_id__isnull=True) |
                    Q(locked_artifact_content_type__isnull=False, locked_artifact_object_id__isnull=False)
                )
            ),
        ]

    def clean(self):
        """Validate placement configuration."""
        # Must have either follow_updates=True or locked_artifact
        if not self.follow_updates and not self.locked_artifact:
            raise ValidationError(
                "Placement must either follow updates or be locked to an artifact"
            )

        # If locked, follow_updates must be False
        if self.locked_artifact and self.follow_updates:
            raise ValidationError(
                "Cannot follow updates when locked to an artifact"
            )

    def save(self, *args, **kwargs):
        """Validate before saving."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        source_str = str(self.source) if self.source else f"{self.source_content_type}"
        target_str = str(self.target) if self.target else f"{self.target_content_type}"
        return f"{source_str} → {target_str} ({self.channel})"
