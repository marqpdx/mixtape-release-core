# dispatch/models.py

from django.utils import timezone
import uuid
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth import get_user_model

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent

User = get_user_model()

class Post(BaseContent):
    # See BaseContent for how attached (sponsor) to (Group, Circle, Event, etc.)

    # Optional visual or banner
    image = models.URLField(blank=True, null=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return f"{self.title or 'Untitled'} by {self.author_display}"


# Dispatch Core

class DispatchDocument(BaseContent):
    """
    Collaborative document with yjs real-time editing.
    Inherits sponsor/author from BaseContent for group integration.

    Note: sponsor fields inherited from BaseContent are made nullable below
    to support migration from old documents without sponsors.
    """
    # BaseContent provides: id, title, slug, sponsor, author, submitted_by, body, published_at

    # Override sponsor fields to make them nullable (for migration from old documents)
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)

    description = models.TextField(blank=True)

    content = models.JSONField(blank=True, default=dict)  # TipTap JSON snapshot

    # yjs collaborative editing state
    yjs_state = models.BinaryField(
        null=True,
        blank=True,
        help_text="Y.Doc binary encoding for collaborative state (CRDT)"
    )
    yjs_state_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time yjs state was synced from Socket.IO service"
    )

    collaborators = models.ManyToManyField(
        User,
        blank=True,
        related_name="dispatch_documents_collaborating"
    )

    is_archived = models.BooleanField(default=False)

    class Meta(BaseContent.Meta):
        verbose_name = "Dispatch Document"
        verbose_name_plural = "Dispatch Documents"

    def __str__(self):
        return self.title or "Untitled Document"

    @property
    def is_published(self):
        """Derive published status from published_at timestamp"""
        return self.published_at is not None



class DispatchDocumentVersion(BaseModel):
    document = models.ForeignKey(DispatchDocument, on_delete=models.CASCADE, related_name='versions')
    content_snapshot = models.JSONField()

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    version_note = models.CharField(max_length=255, blank=True)
    is_manual = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        verbose_name = "Dispatch Document Version"
        verbose_name_plural = "Dispatch Document Versions"

    def __str__(self):
        return f"Version {self.created_at.isoformat()} for {self.document.title}"


class DispatchEditSession(BaseModel):
    document = models.ForeignKey(DispatchDocument, on_delete=models.CASCADE, related_name='edit_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    started_at = models.DateTimeField(default=timezone.now)
    last_active_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Dispatch Edit Session"
        verbose_name_plural = "Dispatch Edit Sessions"

    def __str__(self):
        return f"{self.user} editing {self.document.title}"





