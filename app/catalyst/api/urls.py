# catalyst/api/urls.py

from django.urls import path
from .views import (
    ListRegistersView,
    MaterializeRegistersView,
    ParseFilesView,
    ParseJobStatusView,
    RegisterDetailView,
    StartAnalysisView,
)

urlpatterns = [
    path(
        "groups/<slug:slug>/parse-files/",
        ParseFilesView.as_view(),
        name="catalyst-parse-files",
    ),
    path(
        "groups/<slug:slug>/parse-jobs/<uuid:job_id>/start-analysis/",
        StartAnalysisView.as_view(),
        name="catalyst-start-analysis",
    ),
    path(
        "groups/<slug:slug>/parse-jobs/<uuid:job_id>/status/",
        ParseJobStatusView.as_view(),
        name="catalyst-job-status",
    ),
    path(
        "groups/<slug:slug>/materialize-registers/",
        MaterializeRegistersView.as_view(),
        name="catalyst-materialize-registers",
    ),
    path(
        "groups/<slug:slug>/registers/",
        ListRegistersView.as_view(),
        name="catalyst-list-registers",
    ),
    path(
        "groups/<slug:slug>/registers/<slug:register_slug>/",
        RegisterDetailView.as_view(),
        name="catalyst-register-detail",
    ),
]
