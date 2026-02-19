# earthlab/models/course_item.py

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class CourseItem(BaseModel):
    """
    Join table linking a Course to its ordered content (Libraries or Lessons).

    Uses a GenericForeignKey so a course can contain both:
    - Library instances (used as modules, scope="earthlab_module")
    - Lesson instances (standalone lessons not inside a module)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course = models.ForeignKey(
        "earthlab.Course",
        on_delete=models.CASCADE,
        related_name="items",
    )

    # Polymorphic content reference (Library or Lesson)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    content_object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "content_object_id")

    position = models.PositiveIntegerField()

    section_title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional section heading for visual grouping in course outline",
    )

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "position"],
                name="unique_course_item_position",
            ),
            models.UniqueConstraint(
                fields=["course", "content_type", "content_object_id"],
                name="unique_course_item_content",
            ),
        ]
        indexes = [
            models.Index(fields=["course", "position"]),
            models.Index(fields=["content_type", "content_object_id"]),
        ]

    def __str__(self):
        return f"{self.course} → {self.content_object} (pos {self.position})"
