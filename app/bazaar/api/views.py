# bazaar/api/views.py

"""
Bazaar API Views

ViewSets and Views for Bazaar REST API.
"""

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from bazaar.constants import OfferingStatus, OrderStatus
from bazaar.models import (
    BazaarFulfillmentEvent,
    BazaarOffering,
    BazaarOrder,
    Product,
)
from bazaar.services import (
    BazaarValidationError,
    FulfillmentService,
    OfferingService,
    OrderService,
)
from bazaar.api.permissions import (
    CanCreateOffering,
    IsBuyer,
    IsBuyerOrVendor,
    IsSponsor,
    IsSponsorOrReadOnly,
    IsVendor,
)
from bazaar.api.serializers import (
    FulfillmentEventSerializer,
    OfferingActionSerializer,
    OfferingCreateSerializer,
    OfferingDetailSerializer,
    OfferingListSerializer,
    OfferingUpdateSerializer,
    OrderActionSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    StallSerializer,
)


# =============================================================================
# Product ViewSet
# =============================================================================

class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Product CRUD operations.

    Endpoints:
        GET    /api/bazaar/products/           - List products
        POST   /api/bazaar/products/           - Create product
        GET    /api/bazaar/products/<id>/      - Retrieve product
        PUT    /api/bazaar/products/<id>/      - Update product
        PATCH  /api/bazaar/products/<id>/      - Partial update
        DELETE /api/bazaar/products/<id>/      - Delete product (soft)
    """
    queryset = Product.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    permission_classes = [IsAuthenticated, IsSponsorOrReadOnly]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        elif self.action == "create":
            return ProductCreateSerializer
        return ProductDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Filter by sponsor if provided
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_id = self.request.query_params.get("sponsor_id")

        if sponsor_type and sponsor_id:
            try:
                ct = ContentType.objects.get(model=sponsor_type.lower())
                qs = qs.filter(sponsor_content_type=ct, sponsor_object_id=sponsor_id)
            except ContentType.DoesNotExist:
                pass

        return qs

    def perform_destroy(self, instance):
        """Soft delete."""
        from django.utils import timezone
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])


# =============================================================================
# Offering ViewSet
# =============================================================================

class OfferingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Offering CRUD operations.

    Endpoints:
        GET    /api/bazaar/offerings/                    - List offerings
        POST   /api/bazaar/offerings/                    - Create offering
        GET    /api/bazaar/offerings/<id>/               - Retrieve offering
        PUT    /api/bazaar/offerings/<id>/               - Update offering
        PATCH  /api/bazaar/offerings/<id>/               - Partial update
        DELETE /api/bazaar/offerings/<id>/               - Delete offering (soft)
        POST   /api/bazaar/offerings/<id>/action/        - Perform action (publish, etc.)
    """
    queryset = BazaarOffering.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    permission_classes = [IsAuthenticated, IsSponsorOrReadOnly, CanCreateOffering]

    def get_serializer_class(self):
        if self.action == "list":
            return OfferingListSerializer
        elif self.action == "create":
            return OfferingCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return OfferingUpdateSerializer
        elif self.action == "perform_action":
            return OfferingActionSerializer
        return OfferingDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Filter by status
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Filter by shape
        shape_filter = self.request.query_params.get("shape")
        if shape_filter:
            qs = qs.filter(shape=shape_filter)

        # Filter by sponsor
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_id = self.request.query_params.get("sponsor_id")

        if sponsor_type and sponsor_id:
            try:
                ct = ContentType.objects.get(model=sponsor_type.lower())
                qs = qs.filter(sponsor_content_type=ct, sponsor_object_id=sponsor_id)
            except ContentType.DoesNotExist:
                pass

        # For public listing, only show active offerings
        if self.action == "list" and not self.request.query_params.get("include_drafts"):
            qs = qs.filter(status=OfferingStatus.ACTIVE)

        return qs

    def perform_destroy(self, instance):
        """Soft delete via archive."""
        try:
            OfferingService.archive_offering(instance)
        except BazaarValidationError as e:
            from django.utils import timezone
            instance.deleted_at = timezone.now()
            instance.save(update_fields=["deleted_at", "updated_at"])

    @action(detail=True, methods=["post"], url_path="action")
    def perform_action(self, request, pk=None):
        """
        Perform an action on an offering.

        Actions: publish, pause, resume, archive
        """
        offering = self.get_object()
        serializer = OfferingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_name = serializer.validated_data["action"]

        try:
            if action_name == "publish":
                offering = OfferingService.publish_offering(offering)
            elif action_name == "pause":
                offering = OfferingService.pause_offering(offering)
            elif action_name == "resume":
                offering = OfferingService.resume_offering(offering)
            elif action_name == "archive":
                offering = OfferingService.archive_offering(offering)
            else:
                return Response(
                    {"error": f"Unknown action: {action_name}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(OfferingDetailSerializer(offering).data)

        except BazaarValidationError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )


# =============================================================================
# Order ViewSet
# =============================================================================

class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Order operations.

    Endpoints:
        GET    /api/bazaar/orders/                - List orders (buyer's orders)
        POST   /api/bazaar/orders/                - Create order
        GET    /api/bazaar/orders/<id>/           - Retrieve order
        POST   /api/bazaar/orders/<id>/action/    - Perform action (confirm, etc.)
    """
    queryset = BazaarOrder.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]  # No PUT/PATCH/DELETE

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        elif self.action == "create":
            return OrderCreateSerializer
        elif self.action == "perform_action":
            return OrderActionSerializer
        return OrderDetailSerializer

    def get_permissions(self):
        if self.action == "retrieve":
            return [IsAuthenticated(), IsBuyerOrVendor()]
        if self.action == "perform_action":
            return [IsAuthenticated(), IsBuyerOrVendor()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # Determine view mode
        view_mode = self.request.query_params.get("view", "buyer")

        if view_mode == "vendor":
            # Vendor view: orders for offerings I sponsor
            # This requires more complex filtering
            user_ct = ContentType.objects.get_for_model(user)
            qs = qs.filter(
                offering__sponsor_content_type=user_ct,
                offering__sponsor_object_id=str(user.pk),
            )
        else:
            # Buyer view: my orders
            qs = qs.filter(buyer=user)

        # Filter by status
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs.select_related("offering", "buyer")

    @action(detail=True, methods=["post"], url_path="action")
    def perform_action(self, request, pk=None):
        """
        Perform an action on an order.

        Actions: confirm, start_fulfillment, mark_delivered, complete, cancel
        """
        order = self.get_object()
        serializer = OrderActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_name = serializer.validated_data["action"]
        notes = serializer.validated_data.get("notes", "")

        try:
            if action_name == "confirm":
                order = OrderService.confirm_order(
                    order,
                    stripe_payment_intent_id=serializer.validated_data.get("stripe_payment_intent_id", ""),
                    stripe_charge_id=serializer.validated_data.get("stripe_charge_id", ""),
                )
                # Handle post-confirmation fulfillment
                order = FulfillmentService.handle_order_confirmed(order)

            elif action_name == "start_fulfillment":
                order = FulfillmentService.start_manual_fulfillment(
                    order,
                    actor_user=request.user,
                    notes=notes,
                )

            elif action_name == "mark_delivered":
                order = FulfillmentService.mark_manually_delivered(
                    order,
                    actor_user=request.user,
                    notes=notes,
                )

            elif action_name == "complete":
                order = OrderService.complete_order(order)

            elif action_name == "cancel":
                order = OrderService.cancel_order(
                    order,
                    reason=serializer.validated_data.get("reason", ""),
                    cancelled_by=request.user,
                )

            else:
                return Response(
                    {"error": f"Unknown action: {action_name}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(OrderDetailSerializer(order).data)

        except BazaarValidationError as e:
            return Response(
                {"error": e.message, "code": e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )


# =============================================================================
# Stall View (Virtual)
# =============================================================================

class StallView(generics.RetrieveAPIView):
    """
    View for a vendor's stall (public Bazaar surface).

    A stall is not a database object - it's a computed view of
    active offerings for a sponsor.

    Endpoint:
        GET /api/bazaar/stalls/<sponsor_type>/<sponsor_id>/
    """
    permission_classes = [AllowAny]
    serializer_class = StallSerializer

    def get_object(self):
        sponsor_type = self.kwargs.get("sponsor_type")
        sponsor_id = self.kwargs.get("sponsor_id")

        try:
            ct = ContentType.objects.get(model=sponsor_type.lower())
            sponsor = ct.get_object_for_this_type(pk=sponsor_id)
        except (ContentType.DoesNotExist, Exception):
            from rest_framework.exceptions import NotFound
            raise NotFound("Sponsor not found.")

        # Get active offerings for this sponsor
        offerings = OfferingService.get_active_offerings_for_sponsor(sponsor)

        return {
            "sponsor_id": str(sponsor.pk),
            "sponsor_type": sponsor_type,
            "sponsor_display_name": getattr(sponsor, "display_name", str(sponsor)),
            "offerings": offerings,
            "offerings_count": offerings.count(),
        }


# =============================================================================
# Vendor Dashboard Views
# =============================================================================

class VendorOrdersView(generics.ListAPIView):
    """
    List orders for a vendor (all offerings).

    Endpoint:
        GET /api/bazaar/vendor/orders/
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OrderListSerializer

    def get_queryset(self):
        user = self.request.user

        # Get orders where user is sponsor of the offering
        user_ct = ContentType.objects.get_for_model(user)

        qs = BazaarOrder.objects.filter(
            offering__sponsor_content_type=user_ct,
            offering__sponsor_object_id=str(user.pk),
            deleted_at__isnull=True,
        )

        # Filter by status
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs.select_related("offering", "buyer").order_by("-created_at")


class VendorStatsView(generics.RetrieveAPIView):
    """
    Get vendor statistics.

    Endpoint:
        GET /api/bazaar/vendor/stats/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)

        # Count offerings
        offerings_count = BazaarOffering.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            deleted_at__isnull=True,
        ).count()

        active_offerings_count = BazaarOffering.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            status=OfferingStatus.ACTIVE,
            deleted_at__isnull=True,
        ).count()

        # Count orders
        orders_qs = BazaarOrder.objects.filter(
            offering__sponsor_content_type=user_ct,
            offering__sponsor_object_id=str(user.pk),
            deleted_at__isnull=True,
        )

        pending_orders = orders_qs.filter(status=OrderStatus.PENDING).count()
        confirmed_orders = orders_qs.filter(status=OrderStatus.CONFIRMED).count()
        fulfilling_orders = orders_qs.filter(status=OrderStatus.FULFILLING).count()
        completed_orders = orders_qs.filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED]).count()

        return Response({
            "offerings_count": offerings_count,
            "active_offerings_count": active_offerings_count,
            "orders": {
                "pending": pending_orders,
                "confirmed": confirmed_orders,
                "fulfilling": fulfilling_orders,
                "completed": completed_orders,
                "needs_attention": pending_orders + confirmed_orders + fulfilling_orders,
            },
        })
