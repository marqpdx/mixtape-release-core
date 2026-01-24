# bazaar/services/order_service.py

"""
Bazaar Order Service

Handles all business logic for creating and managing orders.
Implements the order state machine and enforces transition rules.

Order Lifecycle:
    pending → confirmed → fulfilling → delivered → completed
                ↓           ↓           ↓
              cancelled  cancelled   cancelled

Key Invariants:
- Order immutability: once confirmed, key terms are frozen
- Orders must not be deleted; use status transitions
- Snapshot is captured on confirm
"""

from typing import Any, Optional
from django.db import transaction
from django.utils import timezone

from bazaar.constants import OrderStatus
from bazaar.models import BazaarOffering, BazaarOrder
from bazaar.services.validation import BazaarValidator, BazaarValidationError


class OrderService:
    """
    Service for managing BazaarOrder lifecycle.

    All methods are classmethods for stateless operation.
    Use transactions for data integrity.
    """

    # -------------------------------------------------------------------------
    # Create Operations
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def create_order(
        cls,
        offering: BazaarOffering,
        buyer: Any,
        buyer_note: str = "",
        **kwargs,
    ) -> BazaarOrder:
        """
        Create a new order in PENDING status.

        The order captures the effective price at creation time.
        Actual payment happens separately (Stripe integration).

        Args:
            offering: The offering being purchased
            buyer: The user making the purchase
            buyer_note: Optional note from buyer to vendor

        Returns:
            BazaarOrder instance (saved)

        Raises:
            BazaarValidationError: If validation fails
        """
        # Validate offering is purchasable
        BazaarValidator.validate_offering_is_purchasable(offering)

        # Validate buyer is not sponsor (can't buy from yourself)
        BazaarValidator.validate_buyer_not_sponsor(buyer, offering)

        # Calculate amount (effective price at purchase time)
        amount = offering.effective_price
        currency = offering.currency

        # Create the order
        order = BazaarOrder(
            offering=offering,
            buyer=buyer,
            amount=amount,
            currency=currency,
            status=OrderStatus.PENDING,
            buyer_note=buyer_note,
        )

        # Handle any additional kwargs
        for key, value in kwargs.items():
            if hasattr(order, key):
                setattr(order, key, value)

        order.save()
        return order

    # -------------------------------------------------------------------------
    # State Transitions
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def confirm_order(
        cls,
        order: BazaarOrder,
        stripe_payment_intent_id: str = "",
        stripe_charge_id: str = "",
    ) -> BazaarOrder:
        """
        Confirm an order (pending → confirmed).

        Called when payment is captured/committed.
        Captures offering snapshot for audit trail.

        Args:
            order: The order to confirm
            stripe_payment_intent_id: Stripe PaymentIntent ID
            stripe_charge_id: Stripe Charge ID

        Returns:
            Updated order

        Raises:
            BazaarValidationError: If transition is invalid
        """
        BazaarValidator.validate_order_state_transition(
            order.status, OrderStatus.CONFIRMED
        )

        # Capture offering snapshot (immutable record of terms)
        order.capture_offering_snapshot()

        # Update Stripe references
        order.stripe_payment_intent_id = stripe_payment_intent_id
        order.stripe_charge_id = stripe_charge_id

        # Transition status
        order.status = OrderStatus.CONFIRMED
        order.save(update_fields=[
            "status",
            "offering_snapshot",
            "stripe_payment_intent_id",
            "stripe_charge_id",
            "updated_at",
        ])

        return order

    @classmethod
    @transaction.atomic
    def start_fulfillment(cls, order: BazaarOrder) -> BazaarOrder:
        """
        Start fulfillment (confirmed → fulfilling).

        Called when vendor begins work on the order.

        Args:
            order: The order to start fulfilling

        Returns:
            Updated order
        """
        BazaarValidator.validate_order_state_transition(
            order.status, OrderStatus.FULFILLING
        )

        order.status = OrderStatus.FULFILLING
        order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    @transaction.atomic
    def mark_delivered(cls, order: BazaarOrder) -> BazaarOrder:
        """
        Mark order as delivered (fulfilling → delivered).

        Called when the offering's promise has been fulfilled.

        Args:
            order: The order to mark as delivered

        Returns:
            Updated order
        """
        BazaarValidator.validate_order_state_transition(
            order.status, OrderStatus.DELIVERED
        )

        order.status = OrderStatus.DELIVERED
        order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    @transaction.atomic
    def complete_order(cls, order: BazaarOrder) -> BazaarOrder:
        """
        Complete an order (delivered → completed).

        Optional final state. Many orders may remain at 'delivered'.

        Args:
            order: The order to complete

        Returns:
            Updated order
        """
        BazaarValidator.validate_order_state_transition(
            order.status, OrderStatus.COMPLETED
        )

        order.status = OrderStatus.COMPLETED
        order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    @transaction.atomic
    def cancel_order(
        cls,
        order: BazaarOrder,
        reason: str = "",
        cancelled_by: Optional[Any] = None,
    ) -> BazaarOrder:
        """
        Cancel an order (pending/confirmed/fulfilling → cancelled).

        Orders can be cancelled from pending, confirmed, or fulfilling states.
        Delivered and completed orders cannot be cancelled (use refund flow).

        Args:
            order: The order to cancel
            reason: Reason for cancellation
            cancelled_by: User who initiated cancellation

        Returns:
            Updated order

        Raises:
            BazaarValidationError: If order cannot be cancelled
        """
        BazaarValidator.validate_order_state_transition(
            order.status, OrderStatus.CANCELLED
        )

        # Store cancellation info in vendor_note
        cancel_note = f"Cancelled: {reason}" if reason else "Cancelled"
        if cancelled_by:
            cancel_note += f" by {cancelled_by}"
        cancel_note += f" at {timezone.now().isoformat()}"

        if order.vendor_note:
            order.vendor_note += f"\n{cancel_note}"
        else:
            order.vendor_note = cancel_note

        order.status = OrderStatus.CANCELLED
        order.save(update_fields=["status", "vendor_note", "updated_at"])

        # TODO: Trigger refund if payment was captured
        # This will be handled by the Stripe integration layer

        return order

    # -------------------------------------------------------------------------
    # Update Operations
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def add_vendor_note(cls, order: BazaarOrder, note: str) -> BazaarOrder:
        """
        Add a vendor note to the order.

        Args:
            order: The order to update
            note: Note to append

        Returns:
            Updated order
        """
        timestamp = timezone.now().isoformat()
        new_note = f"[{timestamp}] {note}"

        if order.vendor_note:
            order.vendor_note += f"\n{new_note}"
        else:
            order.vendor_note = new_note

        order.save(update_fields=["vendor_note", "updated_at"])
        return order

    # -------------------------------------------------------------------------
    # Query Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def get_orders_for_buyer(cls, buyer: Any, status: Optional[str] = None):
        """
        Get all orders for a buyer.

        Args:
            buyer: The buyer user
            status: Optional status filter

        Returns:
            QuerySet of orders
        """
        qs = BazaarOrder.objects.filter(
            buyer=buyer,
            deleted_at__isnull=True,
        )
        if status:
            qs = qs.filter(status=status)
        return qs.select_related("offering").order_by("-created_at")

    @classmethod
    def get_orders_for_offering(cls, offering: BazaarOffering, status: Optional[str] = None):
        """
        Get all orders for an offering (vendor view).

        Args:
            offering: The offering
            status: Optional status filter

        Returns:
            QuerySet of orders
        """
        qs = BazaarOrder.objects.filter(
            offering=offering,
            deleted_at__isnull=True,
        )
        if status:
            qs = qs.filter(status=status)
        return qs.select_related("buyer").order_by("-created_at")

    @classmethod
    def get_orders_for_sponsor(cls, sponsor: Any, status: Optional[str] = None):
        """
        Get all orders across all offerings for a sponsor (vendor dashboard).

        Args:
            sponsor: The sponsor (Group or User)
            status: Optional status filter

        Returns:
            QuerySet of orders
        """
        from django.contrib.contenttypes.models import ContentType

        sponsor_ct = ContentType.objects.get_for_model(sponsor)

        qs = BazaarOrder.objects.filter(
            offering__sponsor_content_type=sponsor_ct,
            offering__sponsor_object_id=str(sponsor.pk),
            deleted_at__isnull=True,
        )
        if status:
            qs = qs.filter(status=status)
        return qs.select_related("offering", "buyer").order_by("-created_at")

    @classmethod
    def get_pending_orders_count(cls, sponsor: Any) -> int:
        """
        Get count of pending orders for a sponsor (notification badge).

        Args:
            sponsor: The sponsor

        Returns:
            Count of pending orders
        """
        return cls.get_orders_for_sponsor(sponsor, status=OrderStatus.PENDING).count()
