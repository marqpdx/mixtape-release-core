import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class LivingBook(BaseModel):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")

    # Owning context (typically a Group, but polymorphic)
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sponsored_living_books",
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    # The root WritingPiece — its Dispatch is the structural backbone
    trunk = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.PROTECT,
        related_name="living_books_as_trunk",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_living_books",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["trunk"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.title or f"Living Book {self.pk}"


class Branch(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    living_book = models.ForeignKey(
        LivingBook, on_delete=models.CASCADE, related_name='branches'
    )
    anchor_node_id = models.UUIDField(unique=True)
    prompt_text = models.TextField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    parent_branch = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='child_branches'
    )
    is_detached = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        'users.CustomUser', on_delete=models.SET_NULL, null=True,
        related_name='created_branches'
    )

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=['living_book'], name='branch_living_book_idx'),
            models.Index(fields=['anchor_node_id'], name='branch_anchor_node_idx'),
        ]

    def __str__(self):
        return f"Branch {self.anchor_node_id} on {self.living_book_id}"


class LeafCluster(BaseModel):
    MEDIA_TEXT = 'text'
    MEDIA_VOICE = 'voice'
    MEDIA_VIDEO = 'video'
    MEDIA_CHOICES = [
        (MEDIA_TEXT, 'Text'),
        (MEDIA_VOICE, 'Voice'),
        (MEDIA_VIDEO, 'Video'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='leaf_clusters'
    )
    piece = models.ForeignKey(
        'writing.WritingPiece', on_delete=models.CASCADE,
        related_name='leaf_cluster_memberships'
    )
    media_type = models.CharField(
        max_length=20, choices=MEDIA_CHOICES, default=MEDIA_TEXT
    )
    created_by = models.ForeignKey(
        'users.CustomUser', on_delete=models.SET_NULL, null=True,
        related_name='created_leaf_clusters'
    )

    class Meta(BaseModel.Meta):
        unique_together = [('branch', 'piece')]
        indexes = [
            models.Index(fields=['branch'], name='leafcluster_branch_idx'),
            models.Index(fields=['piece'], name='leafcluster_piece_idx'),
        ]

    def __str__(self):
        return f"LeafCluster {self.piece_id} on branch {self.branch_id}"
