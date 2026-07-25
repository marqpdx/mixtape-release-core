# lists/models.py

import hashlib
import uuid

from django.conf import settings
from django.db import models

from fundamentals.models import BaseContent


class List(BaseContent):
    """
    Lightweight text-first list for quick capture in Mill/Grist.

    The body_text field is the canonical representation of the list.
    The right-pane UI is derived from parsing this text.

    Inherits sponsor-scoped slugs from BaseContent - different sponsors
    can each have a list with the same slug.

    Text format (plaintext micro-grammar):
        - item       = open action item
        x item       = completed action item
        * item       = note/bullet (no completion semantics)
        Two-space indent for sub-items (one level only)

    Example:
        - call Alice
        x send report
        * meeting notes
          * discussed Q2 goals
    """

    body_text = models.TextField(
        blank=True,
        default="",
        help_text="Canonical text content of the list (plaintext micro-grammar)",
    )

    # Phase 4: ListItemAnnotation sidecar will store promotion link-backs

    class Meta(BaseContent.Meta):
        verbose_name = "List"
        verbose_name_plural = "Lists"
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"List {self.pk}"


class ListItemAnnotation(models.Model):
    """
    Links a list item to a promoted Project task.

    Uses text hash for matching since item indices can shift as the list is edited.
    The snapshot preserves the original text at promotion time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    list = models.ForeignKey(
        List,
        on_delete=models.CASCADE,
        related_name="annotations",
    )

    # Item identification (hash allows matching even if indices shift)
    item_text_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 hash of normalized item text for matching",
    )
    item_text_snapshot = models.CharField(
        max_length=500,
        help_text="Original item text at promotion time",
    )

    # Link to promoted task
    task = models.ForeignKey(
        "projects.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_annotations",
        help_text="The Project task created from this list item",
    )

    # Tracking
    promoted_at = models.DateTimeField(auto_now_add=True)
    promoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="promoted_list_items",
    )

    class Meta:
        verbose_name = "List Item Annotation"
        verbose_name_plural = "List Item Annotations"
        indexes = [
            models.Index(fields=["list", "item_text_hash"]),
        ]

    def __str__(self):
        return f"{self.list}: {self.item_text_snapshot[:30]}..."

    @staticmethod
    def hash_item_text(text: str) -> str:
        """Generate a hash for matching item text."""
        normalized = text.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()

    @classmethod
    def find_by_text(cls, list_obj, item_text: str):
        """Find an annotation by item text (using hash)."""
        text_hash = cls.hash_item_text(item_text)
        return cls.objects.filter(list=list_obj, item_text_hash=text_hash).first()
