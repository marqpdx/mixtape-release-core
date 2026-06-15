# groups/models/circle.py

from django.db import models


class DeliverableType(models.TextChoices):
    PUDDLEJUMP_DOC = "puddlejump_doc", "Puddlejump Document"
    DISPATCH = "dispatch", "Dispatch"
    FINDING = "finding", "Finding"


class DeliverableStatus(models.TextChoices):
    WORKING = "working", "Working"
    COMPLETE = "complete", "Complete"
    TABLED = "tabled", "Tabled"


class CircleDeliverableIntent(models.Model):
    """
    Stores deliverable tracking fields for a Circle that has the
    hasDeliverableIntent decorator applied. Created by the service layer
    when the decorator is applied; removed when it is removed.
    """
    circle = models.OneToOneField(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="deliverable_intent",
    )
    deliverable_type = models.CharField(
        max_length=20,
        choices=DeliverableType.choices,
    )
    deliverable_status = models.CharField(
        max_length=20,
        choices=DeliverableStatus.choices,
        default=DeliverableStatus.WORKING,
    )

    class Meta:
        verbose_name = "Circle Deliverable Intent"

    def __str__(self):
        return f"{self.circle} — {self.deliverable_type} ({self.deliverable_status})"
