# groups/models/overview_layout.py

import uuid

from django.db import models

from fundamentals.bases import BaseModel


class GroupOverviewLayout(BaseModel):
    """
    Curated layout configuration for a group's Overview tab.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.OneToOneField(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="overview_layout",
    )

    layout_version = models.CharField(max_length=16, default="1")
    blocks = models.JSONField(default=list)

    class Meta:
        ordering = ("-updated_at",)
