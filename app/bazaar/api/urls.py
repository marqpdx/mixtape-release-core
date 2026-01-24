# bazaar/api/urls.py

"""
Bazaar API URL Configuration

Routes:
    /api/bazaar/products/                       - Product CRUD
    /api/bazaar/offerings/                      - Offering CRUD
    /api/bazaar/offerings/<id>/action/          - Offering actions
    /api/bazaar/orders/                         - Order operations
    /api/bazaar/orders/<id>/action/             - Order actions
    /api/bazaar/stalls/<type>/<id>/             - Stall view
    /api/bazaar/vendor/orders/                  - Vendor order list
    /api/bazaar/vendor/stats/                   - Vendor statistics
    /api/bazaar/payments/create-intent/         - Create PaymentIntent
    /api/bazaar/payments/intent/<id>/           - Get PaymentIntent status
    /api/bazaar/payments/cancel-intent/         - Cancel PaymentIntent
    /api/bazaar/payments/refund/                - Create refund
    /api/bazaar/payments/webhook/               - Stripe webhook endpoint
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from bazaar.api.views import (
    OfferingViewSet,
    OrderViewSet,
    ProductViewSet,
    StallView,
    VendorOrdersView,
    VendorStatsView,
)


# Create router for ViewSets
router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="product")
router.register(r"offerings", OfferingViewSet, basename="offering")
router.register(r"orders", OrderViewSet, basename="order")


urlpatterns = [
    # ViewSet routes
    path("", include(router.urls)),

    # Stall view (virtual vendor surface)
    path(
        "stalls/<str:sponsor_type>/<uuid:sponsor_id>/",
        StallView.as_view(),
        name="stall-detail",
    ),

    # Vendor dashboard endpoints
    path(
        "vendor/orders/",
        VendorOrdersView.as_view(),
        name="vendor-orders",
    ),
    path(
        "vendor/stats/",
        VendorStatsView.as_view(),
        name="vendor-stats",
    ),

    # Payment endpoints
    path("payments/", include("bazaar.payments.urls")),
]


# API Documentation
"""
=============================================================================
BAZAAR API REFERENCE
=============================================================================

PRODUCTS
--------
GET    /api/bazaar/products/
       List products (filter: ?sponsor_type=group&sponsor_id=xxx)

POST   /api/bazaar/products/
       Create product
       Body: {
           "title": "Product Name",
           "summary": "Short description",
           "product_type": "physical|digital|service|bundle",
           "sponsor_type": "group",
           "sponsor_id": "uuid"
       }

GET    /api/bazaar/products/<id>/
       Retrieve product details

PUT    /api/bazaar/products/<id>/
       Update product

DELETE /api/bazaar/products/<id>/
       Soft delete product


OFFERINGS
---------
GET    /api/bazaar/offerings/
       List offerings (filter: ?status=active&shape=service&sponsor_type=group&sponsor_id=xxx)
       Add ?include_drafts=true to see draft offerings

POST   /api/bazaar/offerings/
       Create offering (starts in draft)
       Body: {
           "title": "Offering Name",
           "summary": "Short description",
           "shape": "service|event|program|product",
           "price_amount": 1000,  // cents
           "currency": "USD",
           "is_free": false,
           "sponsor_type": "group",
           "sponsor_id": "uuid",
           "asset_type": "product",  // optional
           "asset_id": "uuid"        // optional
       }

GET    /api/bazaar/offerings/<id>/
       Retrieve offering details

PUT    /api/bazaar/offerings/<id>/
       Update offering (restricted fields if published)

POST   /api/bazaar/offerings/<id>/action/
       Perform action on offering
       Body: { "action": "publish|pause|resume|archive" }


ORDERS
------
GET    /api/bazaar/orders/
       List orders (default: buyer view)
       Add ?view=vendor for vendor's orders
       Filter: ?status=pending|confirmed|fulfilling|delivered|completed|cancelled

POST   /api/bazaar/orders/
       Create order
       Body: {
           "offering_id": "uuid",
           "buyer_note": "Optional note"
       }

GET    /api/bazaar/orders/<id>/
       Retrieve order details (buyer or vendor only)

POST   /api/bazaar/orders/<id>/action/
       Perform action on order
       Body: {
           "action": "confirm|start_fulfillment|mark_delivered|complete|cancel",
           "stripe_payment_intent_id": "pi_xxx",  // for confirm
           "notes": "Optional notes",
           "reason": "Cancellation reason"  // for cancel
       }


STALLS (Virtual)
----------------
GET    /api/bazaar/stalls/<sponsor_type>/<sponsor_id>/
       View a vendor's stall (public active offerings)
       Example: /api/bazaar/stalls/group/123e4567-e89b-12d3-a456-426614174000/


VENDOR DASHBOARD
----------------
GET    /api/bazaar/vendor/orders/
       List all orders across vendor's offerings
       Filter: ?status=pending

GET    /api/bazaar/vendor/stats/
       Get vendor statistics (offering counts, order counts)


PAYMENTS (Stripe)
-----------------
POST   /api/bazaar/payments/create-intent/
       Create PaymentIntent for an order
       Body: { "order_id": "uuid" }
       Response: {
           "payment_intent_id": "pi_xxx",
           "client_secret": "pi_xxx_secret_xxx",
           "amount": 1000,
           "currency": "USD"
       }

GET    /api/bazaar/payments/intent/<payment_intent_id>/
       Get PaymentIntent status
       Response: { "id": "pi_xxx", "status": "succeeded", "amount": 1000 }

POST   /api/bazaar/payments/cancel-intent/
       Cancel a PaymentIntent
       Body: { "order_id": "uuid" }

POST   /api/bazaar/payments/refund/
       Create refund (vendor only)
       Body: {
           "order_id": "uuid",
           "amount": 1000,  // optional, partial refund in cents
           "reason": "Customer request"
       }

POST   /api/bazaar/payments/webhook/
       Stripe webhook endpoint (internal use)
       Handles: payment_intent.succeeded, payment_intent.payment_failed,
                charge.refunded, account.updated

=============================================================================
"""
