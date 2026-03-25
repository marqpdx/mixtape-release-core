# workbench/api/urls.py
# No trailing slashes — follows project convention.
#
# Included in groups/api/urls.py as:
#   path("<slug:slug>/workbench/", include(group_workbench_patterns))

from django.urls import path

from . import views
from .pieces import UnifiedPieceListView
from .promotion import WorkingItemPromoteView

group_workbench_patterns = [
    # Unified Piece API (Lane 1 aggregation)
    path("pieces", UnifiedPieceListView.as_view(), name="workbench-pieces"),

    # WorkingItem list + create
    path("working-items", views.WorkingItemListCreateView.as_view(), name="workbench-working-item-list-create"),

    # WorkingItem detail (retrieve, update, delete)
    path("working-items/<uuid:item_id>", views.WorkingItemDetailView.as_view(), name="workbench-working-item-detail"),

    # Autosave
    path("working-items/<uuid:item_id>/autosave", views.WorkingItemAutosaveView.as_view(), name="workbench-working-item-autosave"),

    # Membership — add piece
    path("working-items/<uuid:item_id>/pieces", views.WorkingItemMembershipView.as_view(), name="workbench-working-item-membership"),

    # Membership — reorder pieces
    path("working-items/<uuid:item_id>/pieces/reorder", views.WorkingItemMembershipReorderView.as_view(), name="workbench-working-item-membership-reorder"),

    # Membership — remove piece
    path("working-items/<uuid:item_id>/pieces/<uuid:membership_id>", views.WorkingItemMembershipView.as_view(), name="workbench-working-item-membership-detail"),

    # Promotion
    path("working-items/<uuid:item_id>/promote", WorkingItemPromoteView.as_view(), name="workbench-working-item-promote"),
]
