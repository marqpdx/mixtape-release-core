# bazaar/services/fulfillment_service.py

"""
Bazaar Fulfillment Service

Handles fulfillment actions and creates audit trail events.
Coordinates between OrderService and FulfillmentEvent records.

Fulfillment Types (from architecture):
- Manual: Vendor marks states manually
- Event: Auto-registration on confirm, auto-deliver on event date
- Digital: Immediate access grant on confirm
- Program: Enrollment on confirm, deliver on completion
"""

from typing import Any, Optional
from django.db import transaction
from django.utils import timezone

from bazaar.constants import (
    FulfillmentActorType,
    FulfillmentEventType,
    FulfillmentType,
    OrderStatus,
)
from bazaar.models import BazaarFulfillmentEvent, BazaarOrder
from bazaar.services.order_service import OrderService
from bazaar.services.validation import BazaarValidationError


class FulfillmentService:
    """
    Service for managing order fulfillment and audit trail.

    Wraps OrderService state transitions with fulfillment event logging.
    All methods are classmethods for stateless operation.
    """

    # -------------------------------------------------------------------------
    # Manual Fulfillment Actions
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def start_manual_fulfillment(
        cls,
        order: BazaarOrder,
        actor_user: Any,
        notes: str = "",
    ) -> BazaarOrder:
        """
        Vendor starts working on an order (manual fulfillment).

        Creates a fulfillment event and transitions order to FULFILLING.

        Args:
            order: The order to start fulfilling
            actor_user: The vendor user performing the action
            notes: Optional notes about the fulfillment start

        Returns:
            Updated order
        """
        # Transition order state
        order = OrderService.start_fulfillment(order)

        # Create audit event
        cls._create_event(
            order=order,
            event_type=FulfillmentEventType.STARTED,
            actor_type=FulfillmentActorType.VENDOR,
            actor_user=actor_user,
            notes=notes,
        )

        return order

    @classmethod
    @transaction.atomic
    def mark_manually_delivered(
        cls,
        order: BazaarOrder,
        actor_user: Any,
        notes: str = "",
    ) -> BazaarOrder:
        """
        Vendor marks order as delivered (manual fulfillment).

        Creates a fulfillment event and transitions order to DELIVERED.

        Args:
            order: The order to mark delivered
            actor_user: The vendor user performing the action
            notes: Optional notes about the delivery

        Returns:
            Updated order
        """
        # Transition order state
        order = OrderService.mark_delivered(order)

        # Create audit event
        cls._create_event(
            order=order,
            event_type=FulfillmentEventType.DELIVERED,
            actor_type=FulfillmentActorType.VENDOR,
            actor_user=actor_user,
            notes=notes,
        )

        return order

    # -------------------------------------------------------------------------
    # Automatic Fulfillment Actions
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def auto_fulfill_digital(
        cls,
        order: BazaarOrder,
        notes: str = "",
    ) -> BazaarOrder:
        """
        Automatically fulfill a digital offering.

        Called after payment confirmation for digital offerings.
        Skips FULFILLING state and goes directly to DELIVERED.

        Args:
            order: The confirmed order
            notes: Optional notes (e.g., download link generated)

        Returns:
            Updated order
        """
        if order.status != OrderStatus.CONFIRMED:
            raise BazaarValidationError(
                f"Cannot auto-fulfill order in status {order.status}. Must be CONFIRMED.",
                code="invalid_order_status",
            )

        # For digital, we go directly from confirmed to delivered
        # First transition to fulfilling (required by state machine)
        order.status = OrderStatus.FULFILLING
        order.save(update_fields=["status", "updated_at"])

        # Then immediately to delivered
        order.status = OrderStatus.DELIVERED
        order.save(update_fields=["status", "updated_at"])

        # Create audit event
        cls._create_event(
            order=order,
            event_type=FulfillmentEventType.AUTO_DELIVERED,
            actor_type=FulfillmentActorType.SYSTEM,
            actor_user=None,
            notes=notes or "Digital fulfillment: instant access granted",
        )

        return order

    @classmethod
    @transaction.atomic
    def auto_deliver_event(
        cls,
        order: BazaarOrder,
        notes: str = "",
    ) -> BazaarOrder:
        """
        Automatically deliver an event offering.

        Called when the event date passes (via scheduled task).
        Transitions from FULFILLING to DELIVERED.

        Args:
            order: The order to deliver
            notes: Optional notes about the event

        Returns:
            Updated order
        """
        if order.status != OrderStatus.FULFILLING:
            raise BazaarValidationError(
                f"Cannot auto-deliver order in status {order.status}. Must be FULFILLING.",
                code="invalid_order_status",
            )

        # Transition to delivered
        order = OrderService.mark_delivered(order)

        # Create audit event
        cls._create_event(
            order=order,
            event_type=FulfillmentEventType.AUTO_DELIVERED,
            actor_type=FulfillmentActorType.SYSTEM,
            actor_user=None,
            notes=notes or "Event fulfillment: event completed",
        )

        return order

    # -------------------------------------------------------------------------
    # Post-Confirmation Hooks
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def handle_order_confirmed(cls, order: BazaarOrder) -> BazaarOrder:
        """
        Handle post-confirmation actions based on fulfillment type.

        Called after OrderService.confirm_order().
        Routes to appropriate fulfillment handler.

        Args:
            order: The newly confirmed order

        Returns:
            Updated order (may have advanced state)
        """
        fulfillment_type = order.offering.fulfillment_type

        if fulfillment_type == FulfillmentType.DIGITAL:
            # Digital: immediate delivery
            return cls.auto_fulfill_digital(order)

        elif fulfillment_type == FulfillmentType.EVENT:
            # Event: start fulfillment (registration created)
            # Actual delivery happens when event occurs
            order = OrderService.start_fulfillment(order)
            cls._create_event(
                order=order,
                event_type=FulfillmentEventType.STARTED,
                actor_type=FulfillmentActorType.SYSTEM,
                actor_user=None,
                notes="Event registration created",
            )
            return order

        elif fulfillment_type == FulfillmentType.PROGRAM:
            # Program: start fulfillment (enrollment created)
            # Delivery happens on program completion
            order = OrderService.start_fulfillment(order)
            cls._create_event(
                order=order,
                event_type=FulfillmentEventType.STARTED,
                actor_type=FulfillmentActorType.SYSTEM,
                actor_user=None,
                notes="Program enrollment created",
            )
            return order

        else:
            # Manual: do nothing, vendor will handle
            return order

    # -------------------------------------------------------------------------
    # Query Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def get_fulfillment_history(cls, order: BazaarOrder):
        """
        Get fulfillment event history for an order.

        Args:
            order: The order

        Returns:
            QuerySet of fulfillment events, newest first
        """
        return BazaarFulfillmentEvent.objects.filter(
            order=order,
            deleted_at__isnull=True,
        ).select_related("actor_user").order_by("-created_at")

    @classmethod
    def get_orders_awaiting_fulfillment(cls, sponsor: Any):
        """
        Get orders that need vendor attention.

        Returns orders in CONFIRMED or FULFILLING status.

        Args:
            sponsor: The vendor sponsor

        Returns:
            QuerySet of orders needing attention
        """
        from django.contrib.contenttypes.models import ContentType

        sponsor_ct = ContentType.objects.get_for_model(sponsor)

        return BazaarOrder.objects.filter(
            offering__sponsor_content_type=sponsor_ct,
            offering__sponsor_object_id=str(sponsor.pk),
            offering__fulfillment_type=FulfillmentType.MANUAL,
            status__in=[OrderStatus.CONFIRMED, OrderStatus.FULFILLING],
            deleted_at__isnull=True,
        ).select_related("offering", "buyer").order_by("created_at")

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _create_event(
        cls,
        order: BazaarOrder,
        event_type: str,
        actor_type: str,
        actor_user: Optional[Any],
        notes: str = "",
    ) -> BazaarFulfillmentEvent:
        """
        Create a fulfillment event record.

        Internal helper - not for direct external use.
        """
        return BazaarFulfillmentEvent.objects.create(
            order=order,
            event_type=event_type,
            actor_type=actor_type,
            actor_user=actor_user,
            notes=notes,
        )
