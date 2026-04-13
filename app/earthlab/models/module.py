# earthlab/models/module.py

import uuid

from django.db import models

from fundamentals.bases import BaseModel


class Module(BaseModel):
    """
    EarthLab's owned representation of a learning module.

    Intentionally minimal — foundation for EarthLab's forthcoming refactor (CR-002).
    A Module wraps a Stackroom Library from EarthLab's perspective. The library_id
    is a loose UUID reference; the Library lives in Stackroom and is resolved via
    REST at CP3+.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course = models.ForeignKey(
        "earthlab.Course",
        on_delete=models.CASCADE,
        related_name="modules",
    )

    title = models.CharField(max_length=255, blank=True, default="")

    order_index = models.PositiveIntegerField(default=0)

    # Loose UUID reference to Stackroom Library — resolved via REST at CP3+.
    library_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID reference to Stackroom Library (loose — resolved via REST at CP3+)",
    )

    class Meta:
        ordering = ["course", "order_index"]
        indexes = []

    def __str__(self):
        return self.title or f"Module {str(self.id)[:8]}"
