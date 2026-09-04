# dispatch/models.py

from django.utils import timezone
import uuid
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth import get_user_model

from fundamentals.bases import BaseModel
from fundamentals.mixins import RichBodyMixin
from fundamentals.models import BaseContent
from publishing.models import BaseVersion

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

class DispatchContent(BaseModel):
    """
    Collaborative editing decorator layer - content-type agnostic.

    This is NOT publishable content - it's infrastructure for collaborative editing.
    Can be attached to WorkingDocument, WorkingCourse, or any other working content type.
    Content lives in Yjs; snapshots are synced to the working model.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)

    # Yjs Infrastructure
    yjs_document_id = models.UUIDField(
        unique=True,
        default=uuid.uuid4,
        help_text="Unique identifier for the Yjs document room"
    )
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

    # Collaboration Management
    collaborators = models.ManyToManyField(
        User,
        through='DispatchCollaborator',
        through_fields=('content', 'user'),  # Updated field name
        related_name="dispatch_collaborations",
        help_text="Users who can collaborate on this content"
    )

    # Optional snapshot for non-realtime access
    content_snapshot = models.JSONField(
        blank=True,
        default=dict,
        help_text="Last snapshot of TipTap content from Yjs (for offline viewing)"
    )
    snapshot_updated_at = models.DateTimeField(null=True, blank=True)

    # Lifecycle
    is_archived = models.BooleanField(
        default=False,
        help_text="Mark as archived to hide from active collaboration"
    )

    # Track collaborative edits for rescind feature
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_dispatch_content",
        help_text="User who created this collaboration"
    )
    last_edited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_edited_dispatch_content",
        help_text="User who last edited content"
    )
    last_edited_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When content was last edited"
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Dispatch Content (Collaborative Layer)"
        verbose_name_plural = "Dispatch Content (Collaborative Layers)"
        indexes = [
            models.Index(fields=["yjs_document_id"]),
            models.Index(fields=["is_archived"]),
        ]

    def __str__(self):
        # Get related working document for context
        working_doc = self.working_documents.first()
        if working_doc:
            return f"Collaboration: {working_doc.piece.title or 'Untitled'}"
        return f"Dispatch Content {self.yjs_document_id}"

    @property
    def is_active(self):
        """Check if collaboration is active (not archived)"""
        return not self.is_archived

    # === Role-based Helpers ===

    @property
    def editors(self):
        """Get users who can edit"""
        return self.collaborators.filter(
            collaborator_assignments__role='editor'
        )

    @property
    def commenters(self):
        """Get users who can only comment/review"""
        return self.collaborators.filter(
            collaborator_assignments__role='commenter'
        )

    def can_edit(self, user):
        """Check if user has edit permission"""
        return self.collaborator_assignments.filter(
            user=user,
            role='editor'
        ).exists()

    def can_comment(self, user):
        """Check if user has comment permission (editors can also comment)"""
        return self.collaborator_assignments.filter(
            user=user,
            role__in=['editor', 'commenter']
        ).exists()

    def get_user_role(self, user):
        """Get the role of a specific user, or None if not a collaborator"""
        assignment = self.collaborator_assignments.filter(user=user).first()
        return assignment.role if assignment else None

    # === Rescind Collaboration Helpers ===

    def has_collaborative_edits(self):
        """
        Check if anyone besides the creator has made edits.
        Used to determine if collaboration can be safely rescinded.
        """
        if not self.last_edited_by or not self.created_by:
            return False
        return self.last_edited_by != self.created_by

    def can_be_rescinded(self):
        """
        Check if collaboration can be rescinded.
        Only allowed if no collaborative edits have been made.
        """
        return not self.has_collaborative_edits()

    # === Artifact Resolution (for Publishing) ===

    def get_current_artifact(self):
        """
        Get the latest release snapshot.
        Used by ContentPlacement to resolve follow_updates=True.
        """
        return self.snapshots.filter(kind='release').order_by('-created_at').first()

    def get_artifact(self, ref):
        """
        Get specific snapshot by ID.

        Args:
            ref: UUID (snapshot id)

        Returns:
            DispatchSnapshot instance or None
        """
        return self.snapshots.get(id=ref)


class DispatchCollaborator(BaseModel):
    """
    Through model for managing collaborators on Dispatch content.
    Tracks who can collaborate and their role.
    """
    content = models.ForeignKey(
        DispatchContent,
        on_delete=models.CASCADE,
        related_name="collaborator_assignments"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='dispatch_invites_sent',
        help_text="User who invited this collaborator"
    )

    role = models.CharField(
        max_length=20,
        choices=[
            ('editor', 'Editor'),
            ('commenter', 'Commenter'),
        ],
        default='editor',
        help_text="Editor can edit, Commenter can only comment"
    )

    class Meta(BaseModel.Meta):
        unique_together = [("content", "user")]
        verbose_name = "Dispatch Collaborator"
        verbose_name_plural = "Dispatch Collaborators"

    def __str__(self):
        return f"{self.user} - {self.get_role_display()} on {self.content}"


class DispatchContentVersion(BaseModel):
    content = models.ForeignKey(DispatchContent, on_delete=models.CASCADE, related_name='versions')
    content_snapshot = models.JSONField()

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    version_note = models.CharField(max_length=255, blank=True)
    is_manual = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        verbose_name = "Dispatch Content Version"
        verbose_name_plural = "Dispatch Content Versions"

    def __str__(self):
        return f"Version {self.created_at.isoformat()} for {self.content}"


class DispatchEditSession(BaseModel):
    content = models.ForeignKey(DispatchContent, on_delete=models.CASCADE, related_name='edit_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    started_at = models.DateTimeField(default=timezone.now)
    last_active_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Dispatch Edit Session"
        verbose_name_plural = "Dispatch Edit Sessions"

    def __str__(self):
        return f"{self.user} editing {self.content}"


class DispatchOutlineNode(BaseModel):
    """
    Persistent outline node for a WritingPiece (Dispatch).
    Stored separately from rich text body.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)

    writing_piece = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="outline_nodes",
    )
    title = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    order_index = models.IntegerField(default=0)
    anchor_target = models.UUIDField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["writing_piece_id", "parent_id", "order_index", "created_at"]
        indexes = [
            models.Index(fields=["writing_piece"]),
            models.Index(fields=["parent"]),
            models.Index(fields=["anchor_target"]),
            models.Index(fields=["writing_piece", "parent", "order_index"]),
        ]

    def __str__(self):
        return f"OutlineNode: {self.title} ({self.writing_piece_id})"


class DispatchComment(BaseModel):
    """
    Inline comment on a Dispatch doc (WritingPiece with dispatch_content).
    Anchored to a block by block_id + char offsets within that block.
    Roles: editors can create/resolve; commenters can create but not resolve.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    writing_piece = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="dispatch_comments",
    )
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="dispatch_comments_authored"
    )
    body = models.TextField()

    # Anchor — nullable for document-level (unanchored) comments
    block_id = models.CharField(max_length=64, blank=True, db_index=True)
    anchor_from = models.IntegerField(null=True, blank=True)
    anchor_to = models.IntegerField(null=True, blank=True)
    quoted_text = models.CharField(max_length=512, blank=True)

    # Threading — one level; replies attach to a root comment
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies"
    )

    # Resolution
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatch_comments_resolved",
    )

    class Meta(BaseModel.Meta):
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["writing_piece", "parent"]),
        ]

    @property
    def is_resolved(self):
        return self.resolved_at is not None

    def __str__(self):
        return f"DispatchComment<{self.id}> on {self.writing_piece_id} by {self.author_id}"


class DispatchSnapshot(RichBodyMixin, BaseVersion):
    """
    Immutable snapshot of collaborative DispatchContent.
    Inherits from BaseVersion for universal publishing architecture.

    BaseVersion provides: id, created_at, created_by, kind, label, note, content_hash

    Stores both yjs_state (for exact restoration) and body_json (for rendering/search).
    """
    dispatch_content = models.ForeignKey(
        DispatchContent,
        related_name='snapshots',
        on_delete=models.CASCADE
    )

    # Dual storage for durability and accessibility
    yjs_state = models.BinaryField(
        help_text="Exact collaborative CRDT state for restoration"
    )
    body_json = models.JSONField(
        help_text="Publishable representation (TipTap/ProseMirror JSON)"
    )

    class Meta(BaseVersion.Meta):
        ordering = ['-created_at']
        verbose_name = "Dispatch Snapshot"
        verbose_name_plural = "Dispatch Snapshots"

    def __str__(self):
        doc_str = str(self.dispatch_content) if self.dispatch_content else f"Content #{self.dispatch_content_id}"
        kind_label = self.label or self.kind
        return f"Snapshot ({kind_label}): {doc_str}"
