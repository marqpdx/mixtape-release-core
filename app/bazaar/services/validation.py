# bazaar/services/validation.py

"""
Bazaar Validation Service

Enforces business rules and invariants from the architecture document.
These validations are called by other services before persisting changes.

Key Invariants (from Architecture):
1. Every Offering has exactly one Sponsor
2. Offerings are Contracts, not Assets
3. Bazaar does not own underlying content
4. Governance is decided at capability assignment time
5. Multiple Offerings may reference the same Asset
6. Trust is relational, not reputational
"""

from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType


class BazaarValidationError(Exception):
    """Raised when a Bazaar business rule is violated."""

    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code or "validation_error"
        super().__init__(self.message)


class BazaarValidator:
    """
    Validates Bazaar operations against business rules.

    All validation methods raise BazaarValidationError on failure.
    """

    # -------------------------------------------------------------------------
    # Sponsor Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_sponsor_exists(sponsor: Any) -> None:
        """
        Validate that a sponsor is provided.

        Invariant: Every Offering must have exactly one Sponsor.
        """
        if sponsor is None:
            raise BazaarValidationError(
                "Sponsor is required. Every offering must have exactly one sponsor.",
                code="sponsor_required",
            )

    @staticmethod
    def validate_sponsor_has_bazaar_capability(sponsor: Any) -> None:
        """
        Validate that the sponsor has Bazaar capability (can_sell).

        Invariant: Governance is decided at capability assignment time.
        """
        # Check if sponsor has the can_sell capability
        # This depends on your Group/permissions implementation
        if hasattr(sponsor, "capabilities"):
            if not sponsor.capabilities.get("can_sell", False):
                raise BazaarValidationError(
                    f"Sponsor '{sponsor}' does not have Bazaar capability (can_sell).",
                    code="sponsor_no_capability",
                )
        elif hasattr(sponsor, "can_sell"):
            if not sponsor.can_sell:
                raise BazaarValidationError(
                    f"Sponsor '{sponsor}' does not have Bazaar capability (can_sell).",
                    code="sponsor_no_capability",
                )
        # If no capability system, allow (for v0 flexibility)

    # -------------------------------------------------------------------------
    # Asset-Sponsor Match Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_asset_sponsor_match(
        offering_sponsor: Any,
        offering_sponsor_content_type: ContentType,
        offering_sponsor_object_id: str,
        asset: Any,
    ) -> None:
        """
        Validate that if an offering references an asset with a sponsor,
        the sponsors must match.

        Invariant: Sponsor-match on asset - if offering.asset has a notion
        of sponsor/owner, enforce equality with offering.sponsor.
        """
        if asset is None:
            return  # No asset reference, no validation needed

        # Check if asset has sponsor fields (BaseContent pattern)
        if hasattr(asset, "sponsor_content_type") and hasattr(asset, "sponsor_object_id"):
            asset_sponsor_ct = asset.sponsor_content_type
            asset_sponsor_id = str(asset.sponsor_object_id)

            if (
                asset_sponsor_ct != offering_sponsor_content_type
                or asset_sponsor_id != str(offering_sponsor_object_id)
            ):
                raise BazaarValidationError(
                    f"Offering sponsor must match asset sponsor. "
                    f"Offering sponsor: {offering_sponsor}, Asset sponsor: {asset.sponsor}",
                    code="sponsor_mismatch",
                )

    # -------------------------------------------------------------------------
    # Pricing Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_price(price_amount: int, currency: str, is_free: bool = False) -> None:
        """
        Validate pricing fields.

        Rules:
        - price_amount must be >= 0
        - currency must be a valid 3-letter code
        - If is_free=False and price_amount=0, that's a $0 listing (allowed but unusual)
        """
        if price_amount < 0:
            raise BazaarValidationError(
                "Price amount cannot be negative.",
                code="invalid_price",
            )

        if not currency or len(currency) != 3:
            raise BazaarValidationError(
                f"Currency must be a 3-letter ISO 4217 code, got: '{currency}'",
                code="invalid_currency",
            )

        # Normalize currency to uppercase
        currency = currency.upper()

        # Supported currencies (v0: USD only, expand later)
        supported_currencies = {"USD"}
        if currency not in supported_currencies:
            raise BazaarValidationError(
                f"Currency '{currency}' is not supported. Supported: {supported_currencies}",
                code="unsupported_currency",
            )

    # -------------------------------------------------------------------------
    # Order Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_offering_is_purchasable(offering: Any) -> None:
        """
        Validate that an offering can be purchased.

        Rules:
        - Status must be 'active'
        - (Future: check visibility against buyer's membership)
        """
        from bazaar.constants import OfferingStatus

        if offering.status != OfferingStatus.ACTIVE:
            raise BazaarValidationError(
                f"Offering is not available for purchase. Status: {offering.status}",
                code="offering_not_active",
            )

    @staticmethod
    def validate_buyer_not_sponsor(buyer: Any, offering: Any) -> None:
        """
        Validate that buyer is not the same as the sponsor.

        You typically can't buy from yourself.
        """
        # Check if buyer is the sponsor (for User sponsors)
        if hasattr(offering, "sponsor") and offering.sponsor == buyer:
            raise BazaarValidationError(
                "Cannot purchase your own offering.",
                code="self_purchase",
            )

        # Check via sponsor_object_id for more robust comparison
        if hasattr(offering, "sponsor_object_id") and hasattr(buyer, "pk"):
            if str(offering.sponsor_object_id) == str(buyer.pk):
                # Also check content type matches User
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user_ct = ContentType.objects.get_for_model(User)
                if offering.sponsor_content_type == user_ct:
                    raise BazaarValidationError(
                        "Cannot purchase your own offering.",
                        code="self_purchase",
                    )

    # -------------------------------------------------------------------------
    # State Transition Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_order_state_transition(current_status: str, new_status: str) -> None:
        """
        Validate that an order state transition is allowed.

        Canonical flow: pending → confirmed → fulfilling → delivered → completed
        Special: Any state can transition to cancelled (with restrictions)
        """
        from bazaar.constants import OrderStatus

        # Define valid transitions
        valid_transitions = {
            OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
            OrderStatus.CONFIRMED: {OrderStatus.FULFILLING, OrderStatus.CANCELLED},
            OrderStatus.FULFILLING: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
            OrderStatus.DELIVERED: {OrderStatus.COMPLETED},
            OrderStatus.COMPLETED: set(),  # Terminal state
            OrderStatus.CANCELLED: set(),  # Terminal state
        }

        allowed = valid_transitions.get(current_status, set())

        if new_status not in allowed:
            raise BazaarValidationError(
                f"Invalid order state transition: {current_status} → {new_status}. "
                f"Allowed transitions from {current_status}: {allowed or 'none (terminal state)'}",
                code="invalid_state_transition",
            )

    @staticmethod
    def validate_offering_state_transition(current_status: str, new_status: str) -> None:
        """
        Validate that an offering state transition is allowed.

        Transitions:
        - draft → active (publish)
        - active → unavailable (pause)
        - active → archived (retire)
        - unavailable → active (resume)
        - unavailable → archived (retire)
        - archived → (none, terminal)
        """
        from bazaar.constants import OfferingStatus

        valid_transitions = {
            OfferingStatus.DRAFT: {OfferingStatus.ACTIVE, OfferingStatus.ARCHIVED},
            OfferingStatus.ACTIVE: {OfferingStatus.UNAVAILABLE, OfferingStatus.ARCHIVED},
            OfferingStatus.UNAVAILABLE: {OfferingStatus.ACTIVE, OfferingStatus.ARCHIVED},
            OfferingStatus.ARCHIVED: set(),  # Terminal state
        }

        allowed = valid_transitions.get(current_status, set())

        if new_status not in allowed:
            raise BazaarValidationError(
                f"Invalid offering state transition: {current_status} → {new_status}. "
                f"Allowed transitions from {current_status}: {allowed or 'none (terminal state)'}",
                code="invalid_state_transition",
            )
