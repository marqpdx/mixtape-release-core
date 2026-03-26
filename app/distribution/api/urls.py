# distribution/api/urls.py

from django.urls import path

from .views import (
    DistributeView,
    DistributionHistoryView,
    PublishEventCancelView,
    SourceListView,
)

app_name = "distribution"

urlpatterns = [
    # Sources registry
    path("sources", SourceListView.as_view(), name="source-list"),

    # Per-piece distribution actions (mounted under /api/writing/pieces/<piece_id>/)
    path(
        "pieces/<uuid:piece_id>/distribute",
        DistributeView.as_view(),
        name="piece-distribute",
    ),
    path(
        "pieces/<uuid:piece_id>/publish-events/<uuid:event_id>",
        PublishEventCancelView.as_view(),
        name="publish-event-cancel",
    ),
    path(
        "pieces/<uuid:piece_id>/distribution-history",
        DistributionHistoryView.as_view(),
        name="distribution-history",
    ),
]
