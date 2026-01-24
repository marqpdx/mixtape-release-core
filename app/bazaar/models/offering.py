# bazaar/models/offering.py

"""
Bazaar Offering Model

An Offering is a contract to exchange value. It is NOT the thing being sold.
The Offering answers: Who is accountable? What is offered? What is promised?
What is the price? Is it available?

Bazaar owns the Offering. Other subsystems own the underlying assets.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.models import BaseContent
from bazaar.constants import (
    FulfillmentType,
    OfferingShape,
    OfferingStatus,
    OfferingVisibility,
)


class BazaarOffering(BaseContent):
    """
    A contract to exchange value, optionally referencing an external asset.

    Inherits from BaseContent:
    - id (UUID primary key)
    - sponsor (polymorphic: Group, User, etc.) = vendor of record
    - title, summary, body, slug
    - author, submitted_by
    - tags, categories
    - published_at
    - created_at, updated_at, deleted_at

    Key invariant: sponsor == vendor-of-record == payee
    """

    shape = models.CharField(
        max_length=20,
        choices=OfferingShape.choices,
        help_text="Fulfillment semantics: service, event, program, or product.",
    )

    status = models.CharField(
        max_length=20,
        choices=OfferingStatus.choices,
        default=OfferingStatus.DRAFT,
    )

    visibility = models.CharField(
        max_length=20,
        choices=OfferingVisibility.choices,
        default=OfferingVisibility.PUBLIC,
    )

    # -------------------------------------------------------------------------
    # Optional asset reference (Event, Course, Product, etc.)
    # Supports multi-offering-per-asset: many Offerings can point to same asset
    # -------------------------------------------------------------------------
    asset_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bazaar_offering_assets",
        help_text="Content type of the referenced asset (if any).",
    )
    asset_object_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID of the referenced asset.",
    )
    asset = GenericForeignKey("asset_content_type", "asset_object_id")

    # -------------------------------------------------------------------------
    # Pricing (v0: fixed amount in minor units)
    # -------------------------------------------------------------------------
    price_amount = models.PositiveIntegerField(
        default=0,
        help_text="List price in minor units (smallest currency unit, e.g., cents).",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="ISO 4217 currency code.",
    )

    is_free = models.BooleanField(
        default=False,
        help_text="If True, buyer pays 0 (effective price) without changing list price.",
    )

    # Future pricing expansion (v1+): sliding scale, discounts, promo windows
    price_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Future: promo windows, discounts, sliding scale, pay-what-you-can.",
    )

    # -------------------------------------------------------------------------
    # Fulfillment
    # -------------------------------------------------------------------------
    fulfillment_type = models.CharField(
        max_length=20,
        choices=FulfillmentType.choices,
        default=FulfillmentType.MANUAL,
    )

    # Shape-specific fulfillment settings (v1+)
    fulfillment_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Shape-specific fulfillment settings (v1+).",
    )

    class Meta(BaseContent.Meta):
        verbose_name = "Bazaar Offering"
        verbose_name_plural = "Bazaar Offerings"
        indexes = [
            *getattr(BaseContent.Meta, "indexes", []),
            models.Index(fields=["status", "shape"]),
            models.Index(fields=["asset_content_type", "asset_object_id"]),
            models.Index(fields=["visibility", "status"]),
        ]

    def __str__(self):
        return self.title or f"Offering {self.pk}"

    @property
    def effective_price(self) -> int:
        """Return the price the buyer actually pays (0 if is_free)."""
        return 0 if self.is_free else self.price_amount

    def set_asset(self, asset):
        """Set the polymorphic asset reference."""
        if asset is None:
            self.asset_content_type = None
            self.asset_object_id = None
        else:
            self.asset_content_type = ContentType.objects.get_for_model(asset)
            self.asset_object_id = asset.pk
