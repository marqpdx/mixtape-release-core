# broadcast/api/urls.py
from django.urls import path

from .views import (
    GroupBroadcastDeliveriesView,
    GroupBroadcastDetailView,
    GroupBroadcastListCreateView,
    GroupBroadcastSendView,
    UserBroadcastPreferencesView,
)

# parent path: api/broadcast/
urlpatterns = [
    # Steward broadcast management (scoped to a group)
    path(
        "groups/<slug:slug>/broadcasts/",
        GroupBroadcastListCreateView.as_view(),
        name="broadcast-list-create",
    ),
    path(
        "groups/<slug:slug>/broadcasts/<uuid:pk>/",
        GroupBroadcastDetailView.as_view(),
        name="broadcast-detail",
    ),
    path(
        "groups/<slug:slug>/broadcasts/<uuid:pk>/send/",
        GroupBroadcastSendView.as_view(),
        name="broadcast-send",
    ),
    path(
        "groups/<slug:slug>/broadcasts/<uuid:pk>/deliveries/",
        GroupBroadcastDeliveriesView.as_view(),
        name="broadcast-deliveries",
    ),
    # Member preferences
    path(
        "preferences/",
        UserBroadcastPreferencesView.as_view(),
        name="broadcast-preferences",
    ),
]
