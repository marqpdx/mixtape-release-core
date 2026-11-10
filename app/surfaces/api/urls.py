from django.urls import path

from surfaces.api.views import (
    ArgusBlockDetailView,
    ArgusBlockListView,
    ArgusRunNowView,
    ArgusRunSeriesDetailView,
    ArgusRunSeriesListCreateView,
    ArgusRunSeriesStopView,
)

urlpatterns = [
    path("blocks/", ArgusBlockListView.as_view(), name="argus-blocks"),
    path("blocks/<slug:slug>/", ArgusBlockDetailView.as_view(), name="argus-block-detail"),
    path("blocks/<slug:slug>/run/", ArgusRunNowView.as_view(), name="argus-run-now"),
    path("series/", ArgusRunSeriesListCreateView.as_view(), name="argus-series-create"),
    path("series/<uuid:series_id>/", ArgusRunSeriesDetailView.as_view(), name="argus-series-detail"),
    path("series/<uuid:series_id>/stop/", ArgusRunSeriesStopView.as_view(), name="argus-series-stop"),
]
