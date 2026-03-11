from django.urls import path

from .views import (
    CheckpointView,
    SurfaceDocumentView,
    WorkSessionDetailView,
    WorkSessionItemDeleteView,
    WorkSessionItemListCreateView,
    WorkSessionListCreateView,
)

app_name = "worksessions"

urlpatterns = [
    path("", WorkSessionListCreateView.as_view(), name="session-list-create"),
    path("<uuid:pk>/", WorkSessionDetailView.as_view(), name="session-detail"),
    path(
        "<uuid:pk>/items/",
        WorkSessionItemListCreateView.as_view(),
        name="session-items",
    ),
    path(
        "<uuid:pk>/items/<uuid:item_id>/",
        WorkSessionItemDeleteView.as_view(),
        name="session-item-delete",
    ),
    path(
        "<uuid:pk>/surface/",
        SurfaceDocumentView.as_view(),
        name="session-surface",
    ),
    path(
        "<uuid:pk>/checkpoint/",
        CheckpointView.as_view(),
        name="session-checkpoint",
    ),
]
