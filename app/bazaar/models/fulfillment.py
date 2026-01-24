# bazaar/models/fulfillment.py

"""
Bazaar Fulfillment Event Model

A lightweight audit trail for manual + automated fulfillment.
Optional in v0; provides observability for fulfillment actions.
"""

import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel
from bazaar.constants import FulfillmentActorType, FulfillmentEventType


class BazaarFulfillmentEvent(BaseModel):
    """
    Audit trail entry for fulfillment actions on an order.

    Inherits from BaseModel:
    - created_at, updated_at, deleted_at

    Records who did what and when during fulfillment.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order = models.ForeignKey(
        "bazaar.BazaarOrder",
        on_delete=models.CASCADE,
        related_name="fulfillment_events",
        help_text="The order this event belongs to.",
    )

    actor_type = models.CharField(
        max_length=20,
        choices=FulfillmentActorType.choices,
        default=FulfillmentActorType.SYSTEM,
        help_text="Whether action was by vendor or system.",
    )

    # Optional link to the acting user (for vendor actions)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bazaar_fulfillment_events",
        help_text="User who performed the action (if vendor action).",
    )

    event_type = models.CharField(
        max_length=30,
        choices=FulfillmentEventType.choices,
        help_text="Type of fulfillment event.",
    )

    notes = models.TextField(
        blank=True,
        default="",
        help_text="Optional notes about this fulfillment action.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} on Order {self.order_id}"
