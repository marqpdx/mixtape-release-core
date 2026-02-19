# earthlab/models/lesson.py

from django.db import models

from fundamentals.models import BaseContent
from earthlab.choices import LessonStatus, DifficultyLevel


class Lesson(BaseContent):
    """
    A single lesson — the leaf content unit in EarthLab.

    Inherits from BaseContent:
    - id (UUID), title, slug, summary, body
    - sponsor (GenericFK), author, submitted_by
    - created_at, updated_at

    Rich content is stored in tiptap_json (same format as WritingPiece.body_json).
    """

    status = models.CharField(
        max_length=16,
        choices=LessonStatus.choices,
        default=LessonStatus.DRAFT,
    )
    tiptap_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Rich content in TipTap JSON format",
    )
    estimated_duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Estimated duration in minutes",
    )
    difficulty_level = models.CharField(
        max_length=16,
        choices=DifficultyLevel.choices,
        blank=True,
        default="",
    )

    class Meta(BaseContent.Meta):
        constraints = BaseContent.Meta.constraints + []
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["status", "-updated_at"]),
        ]
        verbose_name = "Lesson"
        verbose_name_plural = "Lessons"

    def __str__(self):
        return self.title or "Untitled Lesson"
