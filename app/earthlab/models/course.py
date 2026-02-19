# earthlab/models/course.py

from django.db import models

from fundamentals.models import BaseContent
from fundamentals.mixins import CuratedSequenceMixin, FlowMode
from earthlab.choices import CourseStatus, DifficultyLevel, DeliveryType


class Course(BaseContent, CuratedSequenceMixin):
    """
    A structured learning experience composed of modules (Libraries) and lessons.

    Inherits from BaseContent:
    - id (UUID), title, slug, summary, body
    - sponsor (GenericFK), author, submitted_by
    - created_at, updated_at

    Inherits from CuratedSequenceMixin:
    - flow_mode (defaults to "sequenced" via save override)
    """

    status = models.CharField(
        max_length=16,
        choices=CourseStatus.choices,
        default=CourseStatus.DRAFT,
    )
    difficulty_level = models.CharField(
        max_length=16,
        choices=DifficultyLevel.choices,
        blank=True,
        default="",
    )
    estimated_duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Estimated duration in minutes",
    )
    learning_objectives = models.JSONField(
        default=list,
        blank=True,
        help_text="List of learning objective strings",
    )
    delivery_type = models.CharField(
        max_length=16,
        choices=DeliveryType.choices,
        default=DeliveryType.SELF_PACED,
    )

    class Meta(BaseContent.Meta):
        constraints = BaseContent.Meta.constraints + []
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["delivery_type"]),
        ]
        verbose_name = "Course"
        verbose_name_plural = "Courses"

    def save(self, *args, **kwargs):
        if not self.flow_mode or self.flow_mode == FlowMode.LOOSE:
            self.flow_mode = FlowMode.SEQUENCED
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title or "Untitled Course"
