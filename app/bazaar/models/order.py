# bazaar/models/order.py

"""
Bazaar Order Model

Orders are transaction records, not content. They have a strict lifecycle
and should never be deleted (for audit/compliance).

Canonical flow: pending → confirmed → fulfilling → delivered → completed
"""

import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel
from bazaar.constants import OrderStatus


class BazaarOrder(BaseModel):
    """
    A buyer's commitment to an Offering.

    Inherits from BaseModel:
    - created_at, updated_at, deleted_at

    Key invariants:
    - Once confirmed, key terms are frozen (use offering_snapshot)
    - Orders must not be deleted; use status transitions instead
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    offering = models.ForeignKey(
        "bazaar.BazaarOffering",
        on_delete=models.PROTECT,
        related_name="orders",
        help_text="The offering being purchased.",
    )

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bazaar_orders",
        help_text="The user making the purchase.",
    )

    # -------------------------------------------------------------------------
    # Money snapshot at time of purchase
    # -------------------------------------------------------------------------
    amount = models.PositiveIntegerField(
        help_text="Amount in minor units (smallest currency unit, e.g., cents).",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="ISO 4217 currency code.",
    )

    # -------------------------------------------------------------------------
    # Order lifecycle
    # -------------------------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )

    # -------------------------------------------------------------------------
    # Notes
    # -------------------------------------------------------------------------
    buyer_note = models.TextField(
        blank=True,
        default="",
        help_text="Optional note from buyer to vendor.",
    )
    vendor_note = models.TextField(
        blank=True,
        default="",
        help_text="Internal note from vendor (not visible to buyer).",
    )

    # -------------------------------------------------------------------------
    # Stripe integration (v0: minimal)
    # -------------------------------------------------------------------------
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Stripe PaymentIntent ID.",
    )
    stripe_charge_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Stripe Charge ID.",
    )

    # -------------------------------------------------------------------------
    # Offering snapshot for audit
    # -------------------------------------------------------------------------
    offering_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Immutable snapshot of offering terms at confirm-time.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["buyer", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["offering", "-created_at"]),
        ]

    def __str__(self):
        return f"Order {self.pk} - {self.status}"

    def delete(self, using=None, keep_parents=False):
        """Orders must not be deleted; use status transitions instead."""
        raise RuntimeError(
            "BazaarOrder records must not be deleted; use status transitions instead."
        )

    @property
    def vendor(self):
        """Return the vendor (sponsor) of the offering."""
        return self.offering.sponsor if self.offering else None

    def capture_offering_snapshot(self):
        """
        Capture current offering state for immutable audit record.
        Call this when order transitions to CONFIRMED.
        """
        if not self.offering:
            return

        self.offering_snapshot = {
            "offering_id": str(self.offering.pk),
            "title": self.offering.title,
            "shape": self.offering.shape,
            "price_amount": self.offering.price_amount,
            "currency": self.offering.currency,
            "is_free": self.offering.is_free,
            "fulfillment_type": self.offering.fulfillment_type,
            "sponsor_id": str(self.offering.sponsor_object_id),
            "sponsor_type": self.offering.sponsor_content_type.model if self.offering.sponsor_content_type else None,
        }
