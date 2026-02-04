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
