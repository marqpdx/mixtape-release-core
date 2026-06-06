from django.urls import path

from ops.api.views import (
    BuildLogEntryListView,
    HealthSnapshotView,
    OpsSummaryView,
    OpsTilesView,
    ProjectStatusView,
)


urlpatterns = [
    path("build-log", BuildLogEntryListView.as_view(), name="ops-build-log"),
    path("health-snapshot", HealthSnapshotView.as_view(), name="ops-health-snapshot"),
    path("project-status", ProjectStatusView.as_view(), name="ops-project-status"),
    path("summary", OpsSummaryView.as_view(), name="ops-summary"),
    path("tiles", OpsTilesView.as_view(), name="ops-tiles"),
]
