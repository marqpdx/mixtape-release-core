# bazaar/payments/urls.py

"""
Bazaar Payment URL Configuration

Note: APPEND_SLASH=False, so no trailing slashes on URLs.

Routes:
    POST /api/bazaar/payments/create-intent            - Create PaymentIntent
    GET  /api/bazaar/payments/intent/<id>              - Get PaymentIntent status
    POST /api/bazaar/payments/cancel-intent            - Cancel PaymentIntent
    POST /api/bazaar/payments/refund                   - Create refund
    POST /api/bazaar/payments/webhook                  - Stripe webhook endpoint
"""

from django.urls import path

from bazaar.payments.views import (
    CancelPaymentIntentView,
    CreatePaymentIntentView,
    PaymentIntentStatusView,
    RefundView,
)
from bazaar.payments.webhooks import stripe_webhook


urlpatterns = [
    # Payment Intent operations
    path(
        "create-intent",
        CreatePaymentIntentView.as_view(),
        name="create-payment-intent",
    ),
    path(
        "intent/<str:payment_intent_id>",
        PaymentIntentStatusView.as_view(),
        name="payment-intent-status",
    ),
    path(
        "cancel-intent",
        CancelPaymentIntentView.as_view(),
        name="cancel-payment-intent",
    ),

    # Refunds
    path(
        "refund",
        RefundView.as_view(),
        name="create-refund",
    ),

    # Stripe webhook
    path(
        "webhook",
        stripe_webhook,
        name="stripe-webhook",
    ),
]
