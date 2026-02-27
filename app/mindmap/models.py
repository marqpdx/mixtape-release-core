# mindmap/models.py

from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent


class MindMap(BaseContent):
    """
    A spatial graph composition surface. First-level BaseContent object.
    Lifecycle: Draft -> Review -> Published -> Archived.
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        REVIEW = "review"
        PUBLISHED = "published"
        ARCHIVED = "archived"

    class ShareMode(models.TextChoices):
        PRIVATE = "private"
        GROUP_READ = "group_read"
        EXPLICIT_GRANTS = "explicit_grants"
        LINK_READ = "link_read"

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    viewport = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=0)
    share_mode = models.CharField(
        max_length=20, choices=ShareMode.choices, default=ShareMode.PRIVATE
    )
    share_token = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"MindMap {self.pk}"


class MindMapNode(BaseModel):
    """
    A node on a mind map canvas. Supports hybrid backing:
    - inline: content stored directly on the node (title, text, primary_url)
    - leaf: content backed by a Leaf FK (canonical content reuse)
    """

    class BackingKind(models.TextChoices):
        INLINE = "inline"
        LEAF = "leaf"

    mind_map = models.ForeignKey(
        MindMap, on_delete=models.CASCADE, related_name="nodes"
    )
    node_type = models.CharField(max_length=32)  # note, link, image, leaf
    pos_x = models.FloatField(default=0)
    pos_y = models.FloatField(default=0)
    width = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    z_index = models.IntegerField(null=True, blank=True)
    collapsed = models.BooleanField(default=False)
    style = models.JSONField(null=True, blank=True)

    # Hybrid backing
    backing_kind = models.CharField(
        max_length=8, choices=BackingKind.choices, default=BackingKind.INLINE
    )
    leaf = models.ForeignKey(
        "writing.Leaf", null=True, blank=True, on_delete=models.SET_NULL
    )

    # Inline content (used when backing_kind = inline)
    title = models.CharField(max_length=255, null=True, blank=True)
    text = models.TextField(null=True, blank=True)
    primary_url = models.URLField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mind_map"]),
            models.Index(fields=["mind_map", "node_type"]),
        ]

    def __str__(self):
        return self.title or f"Node {self.pk}"


class MindMapEdge(BaseModel):
    """
    A relationship between two nodes on a mind map.
    Multiple edges between the same nodes are allowed if edge_type differs.
    """

    mind_map = models.ForeignKey(
        MindMap, on_delete=models.CASCADE, related_name="edges"
    )
    source_node = models.ForeignKey(
        MindMapNode, on_delete=models.CASCADE, related_name="outgoing_edges"
    )
    target_node = models.ForeignKey(
        MindMapNode, on_delete=models.CASCADE, related_name="incoming_edges"
    )
    edge_type = models.CharField(max_length=32)
    label = models.CharField(max_length=255, null=True, blank=True)
    directed = models.BooleanField(default=True)
    style = models.JSONField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mind_map"]),
            models.Index(fields=["source_node"]),
            models.Index(fields=["target_node"]),
        ]

    def __str__(self):
        return f"Edge {self.source_node_id} -> {self.target_node_id}"


class MindMapNodeAttachment(BaseModel):
    """
    An attachment on a mind map node (URL, image, file, embed, or reference).
    Attachments are contextual to the mind map, not canonical Leaf attachments.
    """

    class Kind(models.TextChoices):
        URL = "url"
        IMAGE = "image"
        FILE = "file"
        EMBED = "embed"
        REFERENCE = "reference"

    node = models.ForeignKey(
        MindMapNode, on_delete=models.CASCADE, related_name="attachments"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=255, null=True, blank=True)
    url = models.URLField(null=True, blank=True)
    asset = models.ForeignKey(
        "files.StoredFile", null=True, blank=True, on_delete=models.SET_NULL
    )
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def __str__(self):
        return self.title or f"Attachment {self.pk}"
