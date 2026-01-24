# bazaar/payments/stripe_service.py

"""
Stripe Service for Bazaar

Handles all Stripe API interactions for payment processing.

Architecture:
- Uses Stripe Connect for multi-vendor payouts
- Platform collects payment, transfers to connected accounts
- Supports both direct charges and destination charges

Flow:
1. Buyer creates order → order.status = PENDING
2. Frontend requests PaymentIntent → StripeService.create_payment_intent()
3. Buyer completes payment in frontend (Stripe Elements)
4. Stripe webhook fires → StripeService.handle_payment_success()
5. Order confirmed → order.status = CONFIRMED
"""

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import stripe
from django.conf import settings
from django.db import transaction

from bazaar.models import BazaarOffering, BazaarOrder
from bazaar.constants import OrderStatus
from bazaar.services import OrderService, FulfillmentService
from bazaar.services.validation import BazaarValidationError


logger = logging.getLogger(__name__)


class StripeServiceError(Exception):
    """Raised when a Stripe operation fails."""

    def __init__(self, message: str, code: Optional[str] = None, stripe_error: Optional[Exception] = None):
        self.message = message
        self.code = code or "stripe_error"
        self.stripe_error = stripe_error
        super().__init__(self.message)


class StripeService:
    """
    Service for Stripe payment operations.

    All methods are classmethods for stateless operation.
    Configure Stripe API key in settings.STRIPE_SECRET_KEY.
    """

    # Platform fee percentage (e.g., 0.05 = 5%)
    PLATFORM_FEE_PERCENT = Decimal("0.05")

    @classmethod
    def _get_stripe(cls):
        """Get configured Stripe module."""
        api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise StripeServiceError(
                "Stripe API key not configured. Set STRIPE_SECRET_KEY in settings.",
                code="stripe_not_configured",
            )
        stripe.api_key = api_key
        return stripe

    # -------------------------------------------------------------------------
    # PaymentIntent Operations
    # -------------------------------------------------------------------------

    @classmethod
    def create_payment_intent(
        cls,
        order: BazaarOrder,
        connected_account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe PaymentIntent for an order.

        Args:
            order: The pending order
            connected_account_id: Stripe Connect account ID for the vendor
                                  (optional, for platform with Connect)

        Returns:
            Dict with payment_intent_id and client_secret

        Raises:
            StripeServiceError: If PaymentIntent creation fails
            BazaarValidationError: If order is not in valid state
        """
        if order.status != OrderStatus.PENDING:
            raise BazaarValidationError(
                f"Cannot create PaymentIntent for order in status {order.status}. Must be PENDING.",
                code="invalid_order_status",
            )

        if order.amount == 0:
            # Free order - no payment needed
            return cls._handle_free_order(order)

        stripe_client = cls._get_stripe()

        try:
            # Build PaymentIntent params
            params = {
                "amount": order.amount,
                "currency": order.currency.lower(),
                "metadata": {
                    "order_id": str(order.id),
                    "offering_id": str(order.offering_id),
                    "buyer_id": str(order.buyer_id),
                },
                "description": f"Order {order.id} - {order.offering.title}",
            }

            # If using Stripe Connect, add transfer data
            if connected_account_id:
                platform_fee = int(order.amount * cls.PLATFORM_FEE_PERCENT)
                params["transfer_data"] = {
                    "destination": connected_account_id,
                }
                params["application_fee_amount"] = platform_fee

            # Create PaymentIntent
            payment_intent = stripe_client.PaymentIntent.create(**params)

            # Store PaymentIntent ID on order
            order.stripe_payment_intent_id = payment_intent.id
            order.save(update_fields=["stripe_payment_intent_id", "updated_at"])

            logger.info(f"Created PaymentIntent {payment_intent.id} for order {order.id}")

            return {
                "payment_intent_id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "amount": order.amount,
                "currency": order.currency,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating PaymentIntent: {e}")
            raise StripeServiceError(
                f"Failed to create payment: {e.user_message or str(e)}",
                code="payment_intent_failed",
                stripe_error=e,
            )

    @classmethod
    def _handle_free_order(cls, order: BazaarOrder) -> Dict[str, Any]:
        """
        Handle a free order (no payment required).

        Immediately confirms the order.
        """
        with transaction.atomic():
            OrderService.confirm_order(order)
            FulfillmentService.handle_order_confirmed(order)

        return {
            "payment_intent_id": None,
            "client_secret": None,
            "amount": 0,
            "currency": order.currency,
            "free": True,
            "order_status": order.status,
        }

    @classmethod
    def retrieve_payment_intent(cls, payment_intent_id: str) -> Dict[str, Any]:
        """
        Retrieve a PaymentIntent from Stripe.

        Args:
            payment_intent_id: Stripe PaymentIntent ID

        Returns:
            PaymentIntent data
        """
        stripe_client = cls._get_stripe()

        try:
            payment_intent = stripe_client.PaymentIntent.retrieve(payment_intent_id)
            return {
                "id": payment_intent.id,
                "status": payment_intent.status,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "metadata": payment_intent.metadata,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving PaymentIntent: {e}")
            raise StripeServiceError(
                f"Failed to retrieve payment: {str(e)}",
                code="payment_intent_retrieve_failed",
                stripe_error=e,
            )

    @classmethod
    def cancel_payment_intent(cls, payment_intent_id: str) -> bool:
        """
        Cancel a PaymentIntent.

        Args:
            payment_intent_id: Stripe PaymentIntent ID

        Returns:
            True if cancelled successfully
        """
        stripe_client = cls._get_stripe()

        try:
            stripe_client.PaymentIntent.cancel(payment_intent_id)
            logger.info(f"Cancelled PaymentIntent {payment_intent_id}")
            return True
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling PaymentIntent: {e}")
            return False

    # -------------------------------------------------------------------------
    # Payment Success Handling
    # -------------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def handle_payment_success(
        cls,
        payment_intent_id: str,
        charge_id: Optional[str] = None,
    ) -> BazaarOrder:
        """
        Handle successful payment (webhook callback).

        Confirms the order and triggers fulfillment.

        Args:
            payment_intent_id: Stripe PaymentIntent ID
            charge_id: Stripe Charge ID (optional)

        Returns:
            Confirmed order

        Raises:
            StripeServiceError: If order not found or already processed
        """
        # Find order by PaymentIntent ID
        try:
            order = BazaarOrder.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            raise StripeServiceError(
                f"Order not found for PaymentIntent {payment_intent_id}",
                code="order_not_found",
            )

        # Check if already processed
        if order.status != OrderStatus.PENDING:
            logger.info(f"Order {order.id} already processed (status: {order.status})")
            return order

        # Confirm the order
        order = OrderService.confirm_order(
            order,
            stripe_payment_intent_id=payment_intent_id,
            stripe_charge_id=charge_id or "",
        )

        # Handle post-confirmation fulfillment
        order = FulfillmentService.handle_order_confirmed(order)

        logger.info(f"Order {order.id} confirmed via PaymentIntent {payment_intent_id}")

        return order

    @classmethod
    @transaction.atomic
    def handle_payment_failed(cls, payment_intent_id: str, failure_message: str = "") -> BazaarOrder:
        """
        Handle failed payment.

        Optionally cancels the order or leaves it pending for retry.

        Args:
            payment_intent_id: Stripe PaymentIntent ID
            failure_message: Reason for failure

        Returns:
            Order (may be updated)
        """
        try:
            order = BazaarOrder.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            raise StripeServiceError(
                f"Order not found for PaymentIntent {payment_intent_id}",
                code="order_not_found",
            )

        # Log the failure
        logger.warning(f"Payment failed for order {order.id}: {failure_message}")

        # Add note about failure (don't cancel - allow retry)
        OrderService.add_vendor_note(order, f"Payment failed: {failure_message}")

        return order

    # -------------------------------------------------------------------------
    # Refund Operations (v1)
    # -------------------------------------------------------------------------

    @classmethod
    def create_refund(
        cls,
        order: BazaarOrder,
        amount: Optional[int] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Create a refund for an order.

        Args:
            order: The order to refund
            amount: Amount to refund in minor units (None = full refund)
            reason: Reason for refund

        Returns:
            Refund data

        Raises:
            StripeServiceError: If refund fails
        """
        if not order.stripe_payment_intent_id:
            raise StripeServiceError(
                "Order has no PaymentIntent - cannot refund",
                code="no_payment_intent",
            )

        stripe_client = cls._get_stripe()

        try:
            params = {
                "payment_intent": order.stripe_payment_intent_id,
                "reason": "requested_by_customer",
                "metadata": {
                    "order_id": str(order.id),
                    "refund_reason": reason,
                },
            }

            if amount is not None:
                params["amount"] = amount

            refund = stripe_client.Refund.create(**params)

            logger.info(f"Created refund {refund.id} for order {order.id}")

            return {
                "refund_id": refund.id,
                "amount": refund.amount,
                "status": refund.status,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating refund: {e}")
            raise StripeServiceError(
                f"Failed to create refund: {e.user_message or str(e)}",
                code="refund_failed",
                stripe_error=e,
            )

    # -------------------------------------------------------------------------
    # Stripe Connect (Vendor Onboarding)
    # -------------------------------------------------------------------------

    @classmethod
    def create_connect_account(cls, vendor_email: str, vendor_type: str = "standard") -> Dict[str, Any]:
        """
        Create a Stripe Connect account for a vendor.

        Args:
            vendor_email: Vendor's email address
            vendor_type: "standard", "express", or "custom"

        Returns:
            Connect account data with onboarding link
        """
        stripe_client = cls._get_stripe()

        try:
            account = stripe_client.Account.create(
                type=vendor_type,
                email=vendor_email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            )

            # Create onboarding link
            account_link = stripe_client.AccountLink.create(
                account=account.id,
                refresh_url=f"{settings.FRONTEND_URL}/vendor/stripe/refresh",
                return_url=f"{settings.FRONTEND_URL}/vendor/stripe/complete",
                type="account_onboarding",
            )

            return {
                "account_id": account.id,
                "onboarding_url": account_link.url,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating Connect account: {e}")
            raise StripeServiceError(
                f"Failed to create vendor account: {str(e)}",
                code="connect_account_failed",
                stripe_error=e,
            )

    @classmethod
    def get_connect_account_status(cls, account_id: str) -> Dict[str, Any]:
        """
        Get Stripe Connect account status.

        Args:
            account_id: Stripe Connect account ID

        Returns:
            Account status data
        """
        stripe_client = cls._get_stripe()

        try:
            account = stripe_client.Account.retrieve(account_id)

            return {
                "account_id": account.id,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
                "details_submitted": account.details_submitted,
                "requirements": account.requirements,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving Connect account: {e}")
            raise StripeServiceError(
                f"Failed to retrieve vendor account: {str(e)}",
                code="connect_account_retrieve_failed",
                stripe_error=e,
            )
