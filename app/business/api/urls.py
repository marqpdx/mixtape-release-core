# business/api/urls.py
# No trailing slashes — follows project convention.

from django.urls import path

from . import views

urlpatterns = [
    # Operator-level
    path("clients", views.ClientListView.as_view(), name="business-client-list"),

    # Suppliers
    path("<slug:slug>/suppliers", views.SupplierListCreateView.as_view(), name="business-supplier-list"),
    path("<slug:slug>/suppliers/<uuid:supplier_id>", views.SupplierDetailView.as_view(), name="business-supplier-detail"),

    # Supply Requests
    path("<slug:slug>/supply-requests", views.SupplyRequestListView.as_view(), name="business-supply-request-list"),
    path("<slug:slug>/supply-requests/<uuid:request_id>", views.SupplyRequestDetailView.as_view(), name="business-supply-request-detail"),

    # Fix Items
    path("<slug:slug>/fix-items", views.FixItemListView.as_view(), name="business-fix-item-list"),
    path("<slug:slug>/fix-items/<uuid:fix_item_id>", views.FixItemDetailView.as_view(), name="business-fix-item-detail"),
]
