# bazaar/payments/webhooks.py

"""
Stripe Webhook Handlers

Processes incoming Stripe webhook events for payment status updates.

Security:
- Validates webhook signature using STRIPE_WEBHOOK_SECRET
- Idempotent handling (safe to replay events)
- Logs all events for debugging

Events Handled:
- payment_intent.succeeded: Payment completed successfully
- payment_intent.payment_failed: Payment failed
- charge.refunded: Refund processed
- account.updated: Connect account status changed
"""

import json
import logging
from typing import Any, Dict, Optional

import stripe
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from bazaar.payments.stripe_service import StripeService, StripeServiceError


logger = logging.getLogger(__name__)


class WebhookError(Exception):
    """Raised when webhook processing fails."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """
    Verify Stripe webhook signature and construct event.

    Args:
        payload: Raw request body
        sig_header: Stripe-Signature header value

    Returns:
        Verified Stripe Event object

    Raises:
        WebhookError: If signature verification fails
    """
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

    if not webhook_secret:
        raise WebhookError(
            "Stripe webhook secret not configured. Set STRIPE_WEBHOOK_SECRET in settings.",
            status_code=500,
        )

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            webhook_secret,
        )
        return event
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise WebhookError("Invalid payload", status_code=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise WebhookError("Invalid signature", status_code=400)


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """
    Main Stripe webhook endpoint.

    POST /api/bazaar/payments/webhook/

    Verifies signature and routes to appropriate handler.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except WebhookError as e:
        return HttpResponse(e.message, status=e.status_code)

    event_type = event.type
    event_data = event.data.object

    logger.info(f"Processing Stripe webhook: {event_type} ({event.id})")

    # Route to handler
    handlers = {
        "payment_intent.succeeded": handle_payment_intent_succeeded,
        "payment_intent.payment_failed": handle_payment_intent_failed,
        "charge.refunded": handle_charge_refunded,
        "account.updated": handle_account_updated,
    }

    handler = handlers.get(event_type)

    if handler:
        try:
            handler(event_data)
            logger.info(f"Successfully processed {event_type}")
        except StripeServiceError as e:
            logger.error(f"Service error processing {event_type}: {e.message}")
            # Return 200 to prevent Stripe retries for business logic errors
            return HttpResponse(f"Error: {e.message}", status=200)
        except Exception as e:
            logger.exception(f"Unexpected error processing {event_type}: {e}")
            # Return 500 so Stripe will retry
            return HttpResponse("Internal error", status=500)
    else:
        logger.info(f"Unhandled event type: {event_type}")

    return HttpResponse("OK", status=200)


# -----------------------------------------------------------------------------
# Event Handlers
# -----------------------------------------------------------------------------


def handle_payment_intent_succeeded(payment_intent: Dict[str, Any]) -> None:
    """
    Handle successful payment.

    Updates order status and triggers fulfillment.
    """
    payment_intent_id = payment_intent.get("id")
    charge_id = None

    # Get charge ID from the latest charge
    charges = payment_intent.get("charges", {})
    if charges and charges.get("data"):
        charge_id = charges["data"][0].get("id")

    logger.info(f"Payment succeeded: {payment_intent_id}")

    StripeService.handle_payment_success(
        payment_intent_id=payment_intent_id,
        charge_id=charge_id,
    )


def handle_payment_intent_failed(payment_intent: Dict[str, Any]) -> None:
    """
    Handle failed payment.

    Logs failure and optionally notifies buyer.
    """
    payment_intent_id = payment_intent.get("id")
    last_error = payment_intent.get("last_payment_error", {})
    failure_message = last_error.get("message", "Payment failed")

    logger.warning(f"Payment failed: {payment_intent_id} - {failure_message}")

    StripeService.handle_payment_failed(
        payment_intent_id=payment_intent_id,
        failure_message=failure_message,
    )


def handle_charge_refunded(charge: Dict[str, Any]) -> None:
    """
    Handle refund completion.

    Updates order status if fully refunded.
    """
    charge_id = charge.get("id")
    payment_intent_id = charge.get("payment_intent")
    amount_refunded = charge.get("amount_refunded", 0)
    amount_captured = charge.get("amount_captured", 0)
    fully_refunded = charge.get("refunded", False)

    logger.info(
        f"Charge refunded: {charge_id}, "
        f"amount_refunded={amount_refunded}, "
        f"fully_refunded={fully_refunded}"
    )

    # Find and update the order
    if payment_intent_id:
        from bazaar.models import BazaarOrder
        from bazaar.services import OrderService

        try:
            order = BazaarOrder.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                deleted_at__isnull=True,
            )

            if fully_refunded:
                # Add note about full refund
                OrderService.add_vendor_note(
                    order,
                    f"Full refund processed: {amount_refunded / 100:.2f} {order.currency}",
                )
                # Optionally cancel the order
                # OrderService.cancel_order(order, reason="Full refund processed")
            else:
                # Partial refund - just add note
                OrderService.add_vendor_note(
                    order,
                    f"Partial refund processed: {amount_refunded / 100:.2f} {order.currency}",
                )

        except BazaarOrder.DoesNotExist:
            logger.warning(f"Order not found for PaymentIntent {payment_intent_id}")


def handle_account_updated(account: Dict[str, Any]) -> None:
    """
    Handle Stripe Connect account updates.

    Updates vendor's payment capability status.
    """
    account_id = account.get("id")
    charges_enabled = account.get("charges_enabled", False)
    payouts_enabled = account.get("payouts_enabled", False)
    details_submitted = account.get("details_submitted", False)

    logger.info(
        f"Account updated: {account_id}, "
        f"charges_enabled={charges_enabled}, "
        f"payouts_enabled={payouts_enabled}"
    )

    # TODO: Update vendor's payment status in the database
    # This would require a VendorPaymentProfile model or similar
    # For now, just log the status change


# -----------------------------------------------------------------------------
# Checkout Session Handlers (optional, for Checkout integration)
# -----------------------------------------------------------------------------


def handle_checkout_session_completed(session: Dict[str, Any]) -> None:
    """
    Handle Checkout Session completion.

    Used if using Stripe Checkout instead of custom PaymentIntent flow.
    """
    session_id = session.get("id")
    payment_intent_id = session.get("payment_intent")
    metadata = session.get("metadata", {})

    logger.info(f"Checkout completed: {session_id}")

    if payment_intent_id:
        StripeService.handle_payment_success(
            payment_intent_id=payment_intent_id,
        )
