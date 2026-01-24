# bazaar/payments/__init__.py

"""
Bazaar Payments Package

Stripe integration for Bazaar payment processing.

Usage:
    from bazaar.payments import StripeService

    # Create payment intent for an order
    payment_intent = StripeService.create_payment_intent(order)

    # Confirm order after successful payment
    StripeService.handle_payment_success(payment_intent_id)

Webhook:
    Configure Stripe to send webhooks to:
    POST /api/bazaar/payments/webhook/

    Required settings:
    - STRIPE_SECRET_KEY: Your Stripe secret key
    - STRIPE_WEBHOOK_SECRET: Webhook signing secret
"""

from bazaar.payments.stripe_service import StripeService, StripeServiceError

__all__ = ["StripeService", "StripeServiceError"]
