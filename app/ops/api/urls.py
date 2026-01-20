from django.urls import path

from ops.api.views import HealthSnapshotView, OpsSummaryView, OpsTilesView


urlpatterns = [
    path("health-snapshot", HealthSnapshotView.as_view(), name="ops-health-snapshot"),
    path("summary", OpsSummaryView.as_view(), name="ops-summary"),
    path("tiles", OpsTilesView.as_view(), name="ops-tiles"),
]
