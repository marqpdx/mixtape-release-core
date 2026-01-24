# bazaar/services/__init__.py

"""
Bazaar Service Layer

Business logic for Bazaar operations. Services enforce invariants
from the architecture document and handle complex workflows.

Usage:
    from bazaar.services import OfferingService, OrderService

    # Create and publish an offering
    offering = OfferingService.create_offering(sponsor=group, ...)
    OfferingService.publish_offering(offering)

    # Create and confirm an order
    order = OrderService.create_order(offering=offering, buyer=user)
    OrderService.confirm_order(order, stripe_payment_intent_id="pi_xxx")
"""

from bazaar.services.offering_service import OfferingService
from bazaar.services.order_service import OrderService
from bazaar.services.fulfillment_service import FulfillmentService
from bazaar.services.validation import BazaarValidationError

__all__ = [
    "OfferingService",
    "OrderService",
    "FulfillmentService",
    "BazaarValidationError",
]
