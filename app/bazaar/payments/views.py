# bazaar/payments/views.py

"""
Bazaar Payment Views

API endpoints for payment operations.

Endpoints:
    POST /api/bazaar/payments/create-intent/     - Create PaymentIntent for order
    GET  /api/bazaar/payments/intent/<id>/       - Get PaymentIntent status
    POST /api/bazaar/payments/cancel-intent/     - Cancel PaymentIntent
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bazaar.models import BazaarOrder
from bazaar.payments.stripe_service import StripeService, StripeServiceError
from bazaar.services.validation import BazaarValidationError


logger = logging.getLogger(__name__)


class CreatePaymentIntentView(APIView):
    """
    Create a Stripe PaymentIntent for an order.

    POST /api/bazaar/payments/create-intent/

    Request body:
        {
            "order_id": "uuid"
        }

    Response:
        {
            "payment_intent_id": "pi_xxx",
            "client_secret": "pi_xxx_secret_xxx",
            "amount": 1000,
            "currency": "USD"
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")

        if not order_id:
            return Response(
                {"error": "order_id is required", "code": "missing_order_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the order
        try:
            order = BazaarOrder.objects.get(
                id=order_id,
                buyer=request.user,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            return Response(
                {"error": "Order not found", "code": "order_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get connected account ID if vendor has one
        connected_account_id = self._get_vendor_stripe_account(order)

        try:
            result = StripeService.create_payment_intent(
                order=order,
                connected_account_id=connected_account_id,
            )
            return Response(result)

        except BazaarValidationError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except StripeServiceError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _get_vendor_stripe_account(self, order) -> str | None:
        """
        Get the Stripe Connect account ID for the vendor.

        Returns None if vendor doesn't have Stripe Connect set up.
        """
        sponsor = order.offering.sponsor
        if hasattr(sponsor, "stripe_connect_account_id"):
            return sponsor.stripe_connect_account_id
        return None


class PaymentIntentStatusView(APIView):
    """
    Get PaymentIntent status.

    GET /api/bazaar/payments/intent/<payment_intent_id>/

    Response:
        {
            "id": "pi_xxx",
            "status": "succeeded",
            "amount": 1000,
            "currency": "usd"
        }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, payment_intent_id):
        # Verify user has access to this payment intent
        try:
            order = BazaarOrder.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            return Response(
                {"error": "Payment not found", "code": "payment_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if user is buyer or vendor
        if not self._can_view_order(request.user, order):
            return Response(
                {"error": "Access denied", "code": "access_denied"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = StripeService.retrieve_payment_intent(payment_intent_id)
            return Response(result)

        except StripeServiceError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _can_view_order(self, user, order) -> bool:
        """Check if user can view this order's payment details."""
        # Buyer can view
        if order.buyer == user:
            return True

        # Vendor can view
        from django.contrib.contenttypes.models import ContentType

        user_ct = ContentType.objects.get_for_model(user)
        offering = order.offering

        if (
            offering.sponsor_content_type == user_ct
            and str(offering.sponsor_object_id) == str(user.pk)
        ):
            return True

        return False


class CancelPaymentIntentView(APIView):
    """
    Cancel a PaymentIntent.

    POST /api/bazaar/payments/cancel-intent/

    Request body:
        {
            "order_id": "uuid"
        }

    Response:
        {
            "success": true,
            "message": "Payment cancelled"
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")

        if not order_id:
            return Response(
                {"error": "order_id is required", "code": "missing_order_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the order (only buyer can cancel)
        try:
            order = BazaarOrder.objects.get(
                id=order_id,
                buyer=request.user,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            return Response(
                {"error": "Order not found", "code": "order_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not order.stripe_payment_intent_id:
            return Response(
                {"error": "No payment to cancel", "code": "no_payment_intent"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success = StripeService.cancel_payment_intent(order.stripe_payment_intent_id)

        if success:
            return Response({
                "success": True,
                "message": "Payment cancelled",
            })
        else:
            return Response(
                {"error": "Failed to cancel payment", "code": "cancel_failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class RefundView(APIView):
    """
    Create a refund for an order.

    POST /api/bazaar/payments/refund/

    Request body:
        {
            "order_id": "uuid",
            "amount": 1000,  // optional, minor units (cents)
            "reason": "Customer request"
        }

    Response:
        {
            "refund_id": "re_xxx",
            "amount": 1000,
            "status": "succeeded"
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")
        amount = request.data.get("amount")  # Optional partial refund
        reason = request.data.get("reason", "")

        if not order_id:
            return Response(
                {"error": "order_id is required", "code": "missing_order_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the order
        try:
            order = BazaarOrder.objects.get(
                id=order_id,
                deleted_at__isnull=True,
            )
        except BazaarOrder.DoesNotExist:
            return Response(
                {"error": "Order not found", "code": "order_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only vendor can refund
        if not self._is_vendor(request.user, order):
            return Response(
                {"error": "Only vendor can issue refunds", "code": "not_vendor"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = StripeService.create_refund(
                order=order,
                amount=amount,
                reason=reason,
            )
            return Response(result)

        except StripeServiceError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _is_vendor(self, user, order) -> bool:
        """Check if user is the vendor for this order."""
        from django.contrib.contenttypes.models import ContentType

        user_ct = ContentType.objects.get_for_model(user)
        offering = order.offering

        if (
            offering.sponsor_content_type == user_ct
            and str(offering.sponsor_object_id) == str(user.pk)
        ):
            return True

        # Check group membership
        if offering.sponsor_content_type.model == "group":
            try:
                group = offering.sponsor
                if hasattr(group, "memberships"):
                    membership = group.memberships.filter(
                        user=user,
                        role__in=["admin", "steward"],
                        deleted_at__isnull=True,
                    ).first()
                    return membership is not None
            except Exception:
                pass

        return False
