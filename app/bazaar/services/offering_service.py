# bazaar/services/offering_service.py

"""
Bazaar Offering Service

Handles all business logic for creating, updating, and managing offerings.
Enforces invariants and coordinates with validation service.
"""

from typing import Any, Optional
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from bazaar.constants import (
    FulfillmentType,
    OfferingShape,
    OfferingStatus,
    OfferingVisibility,
)
from bazaar.models import BazaarOffering, Product
from bazaar.services.validation import BazaarValidator, BazaarValidationError


class OfferingService:
    """
    Service for managing BazaarOffering lifecycle.

    All methods are classmethods for stateless operation.
    Use transactions for data integrity.
    """

    # -------------------------------------------------------------------------
    # Create Operations
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def create_offering(
        cls,
        sponsor: Any,
        title: str,
        shape: str,
        price_amount: int = 0,
        currency: str = "USD",
        is_free: bool = False,
        summary: str = "",
        body: str = "",
        visibility: str = OfferingVisibility.PUBLIC,
        fulfillment_type: str = FulfillmentType.MANUAL,
        asset: Optional[Any] = None,
        submitted_by: Optional[Any] = None,
        author: Optional[Any] = None,
        **kwargs,
    ) -> BazaarOffering:
        """
        Create a new offering in DRAFT status.

        Args:
            sponsor: The vendor (Group or User) responsible for this offering
            title: Display title for the offering
            shape: Offering shape (service, event, program, product)
            price_amount: Price in minor units (cents). Default 0.
            currency: ISO 4217 currency code. Default USD.
            is_free: If True, effective price is 0 regardless of price_amount
            summary: Short description
            body: Full description/details
            visibility: Who can see this offering
            fulfillment_type: How the offering is fulfilled
            asset: Optional referenced asset (Product, Event, etc.)
            submitted_by: User who created this record
            author: User who authored the content (may differ from submitted_by)

        Returns:
            BazaarOffering instance (saved)

        Raises:
            BazaarValidationError: If validation fails
        """
        # Validate sponsor
        BazaarValidator.validate_sponsor_exists(sponsor)

        # Validate pricing
        BazaarValidator.validate_price(price_amount, currency, is_free)

        # Validate shape
        if shape not in [s.value for s in OfferingShape]:
            raise BazaarValidationError(
                f"Invalid shape: {shape}. Must be one of: {[s.value for s in OfferingShape]}",
                code="invalid_shape",
            )

        # Get sponsor content type
        sponsor_content_type = ContentType.objects.get_for_model(sponsor)
        sponsor_object_id = str(sponsor.pk)

        # Validate asset-sponsor match if asset provided
        if asset is not None:
            BazaarValidator.validate_asset_sponsor_match(
                offering_sponsor=sponsor,
                offering_sponsor_content_type=sponsor_content_type,
                offering_sponsor_object_id=sponsor_object_id,
                asset=asset,
            )

        # Create the offering
        offering = BazaarOffering(
            title=title,
            summary=summary,
            body=body,
            shape=shape,
            status=OfferingStatus.DRAFT,
            visibility=visibility,
            price_amount=price_amount,
            currency=currency.upper(),
            is_free=is_free,
            fulfillment_type=fulfillment_type,
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
            submitted_by=submitted_by,
            author=author,
        )

        # Set asset reference if provided
        if asset is not None:
            offering.set_asset(asset)

        # Handle any additional kwargs (for extensibility)
        for key, value in kwargs.items():
            if hasattr(offering, key):
                setattr(offering, key, value)

        offering.save()
        return offering

    @classmethod
    @transaction.atomic
    def create_product_offering(
        cls,
        sponsor: Any,
        product: Product,
        title: Optional[str] = None,
        price_amount: int = 0,
        currency: str = "USD",
        **kwargs,
    ) -> BazaarOffering:
        """
        Convenience method to create an offering for a Product.

        Args:
            sponsor: The vendor
            product: The Product asset to reference
            title: Optional title (defaults to product title)
            price_amount: Price in minor units
            currency: Currency code

        Returns:
            BazaarOffering for the product
        """
        return cls.create_offering(
            sponsor=sponsor,
            title=title or product.title,
            shape=OfferingShape.PRODUCT,
            price_amount=price_amount,
            currency=currency,
            asset=product,
            summary=product.summary,
            **kwargs,
        )

    # -------------------------------------------------------------------------
    # State Transitions
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def publish_offering(cls, offering: BazaarOffering) -> BazaarOffering:
        """
        Publish an offering (draft → active).

        Args:
            offering: The offering to publish

        Returns:
            Updated offering

        Raises:
            BazaarValidationError: If transition is invalid
        """
        BazaarValidator.validate_offering_state_transition(
            offering.status, OfferingStatus.ACTIVE
        )

        offering.status = OfferingStatus.ACTIVE
        offering.published_at = timezone.now()
        offering.save(update_fields=["status", "published_at", "updated_at"])

        return offering

    @classmethod
    @transaction.atomic
    def pause_offering(cls, offering: BazaarOffering) -> BazaarOffering:
        """
        Pause an offering (active → unavailable).

        Makes the offering temporarily unavailable for purchase.

        Args:
            offering: The offering to pause

        Returns:
            Updated offering
        """
        BazaarValidator.validate_offering_state_transition(
            offering.status, OfferingStatus.UNAVAILABLE
        )

        offering.status = OfferingStatus.UNAVAILABLE
        offering.save(update_fields=["status", "updated_at"])

        return offering

    @classmethod
    @transaction.atomic
    def resume_offering(cls, offering: BazaarOffering) -> BazaarOffering:
        """
        Resume a paused offering (unavailable → active).

        Args:
            offering: The offering to resume

        Returns:
            Updated offering
        """
        BazaarValidator.validate_offering_state_transition(
            offering.status, OfferingStatus.ACTIVE
        )

        offering.status = OfferingStatus.ACTIVE
        offering.save(update_fields=["status", "updated_at"])

        return offering

    @classmethod
    @transaction.atomic
    def archive_offering(cls, offering: BazaarOffering) -> BazaarOffering:
        """
        Archive an offering (any non-archived → archived).

        Archived offerings are no longer available and cannot be reactivated.

        Args:
            offering: The offering to archive

        Returns:
            Updated offering
        """
        BazaarValidator.validate_offering_state_transition(
            offering.status, OfferingStatus.ARCHIVED
        )

        offering.status = OfferingStatus.ARCHIVED
        offering.save(update_fields=["status", "updated_at"])

        return offering

    # -------------------------------------------------------------------------
    # Update Operations
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def update_offering(
        cls,
        offering: BazaarOffering,
        **updates,
    ) -> BazaarOffering:
        """
        Update offering fields.

        Only certain fields can be updated depending on status.
        Active offerings have restricted updates.

        Args:
            offering: The offering to update
            **updates: Field updates

        Returns:
            Updated offering
        """
        # Fields that can always be updated
        always_editable = {"summary", "body", "visibility", "fulfillment_config", "price_config"}

        # Fields that can only be updated in draft
        draft_only = {"shape", "price_amount", "currency", "is_free", "fulfillment_type"}

        # Validate field editability
        for field in updates:
            if field in draft_only and offering.status != OfferingStatus.DRAFT:
                raise BazaarValidationError(
                    f"Field '{field}' can only be updated when offering is in draft status.",
                    code="field_not_editable",
                )

        # Validate pricing if being updated
        if "price_amount" in updates or "currency" in updates:
            BazaarValidator.validate_price(
                updates.get("price_amount", offering.price_amount),
                updates.get("currency", offering.currency),
                updates.get("is_free", offering.is_free),
            )

        # Apply updates
        update_fields = ["updated_at"]
        for field, value in updates.items():
            if hasattr(offering, field):
                setattr(offering, field, value)
                update_fields.append(field)

        offering.save(update_fields=update_fields)
        return offering

    @classmethod
    @transaction.atomic
    def set_offering_asset(
        cls,
        offering: BazaarOffering,
        asset: Optional[Any],
    ) -> BazaarOffering:
        """
        Set or clear the asset reference for an offering.

        Args:
            offering: The offering to update
            asset: The asset to reference (or None to clear)

        Returns:
            Updated offering
        """
        if offering.status != OfferingStatus.DRAFT:
            raise BazaarValidationError(
                "Asset can only be changed when offering is in draft status.",
                code="asset_not_editable",
            )

        if asset is not None:
            BazaarValidator.validate_asset_sponsor_match(
                offering_sponsor=offering.sponsor,
                offering_sponsor_content_type=offering.sponsor_content_type,
                offering_sponsor_object_id=offering.sponsor_object_id,
                asset=asset,
            )

        offering.set_asset(asset)
        offering.save(update_fields=["asset_content_type", "asset_object_id", "updated_at"])

        return offering

    # -------------------------------------------------------------------------
    # Query Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def get_active_offerings_for_sponsor(cls, sponsor: Any):
        """
        Get all active offerings for a sponsor (stall view).

        Args:
            sponsor: The sponsor (Group or User)

        Returns:
            QuerySet of active offerings
        """
        sponsor_ct = ContentType.objects.get_for_model(sponsor)
        return BazaarOffering.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=str(sponsor.pk),
            status=OfferingStatus.ACTIVE,
            deleted_at__isnull=True,
        ).order_by("-published_at")

    @classmethod
    def get_offerings_by_asset(cls, asset: Any):
        """
        Get all offerings that reference a specific asset.

        Args:
            asset: The asset to find offerings for

        Returns:
            QuerySet of offerings referencing this asset
        """
        asset_ct = ContentType.objects.get_for_model(asset)
        return BazaarOffering.objects.filter(
            asset_content_type=asset_ct,
            asset_object_id=str(asset.pk),
            deleted_at__isnull=True,
        )
