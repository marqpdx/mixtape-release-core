from django.urls import path

from .views import (
    InsightCreateView,
    IntakeResponseSaveView,
    IntakeSessionCreateView,
    IntakeSessionDetailInternalView,
    IntakeSessionDetailView,
    IntakeSubmitView,
    NoteCreateView,
    ProspectDetailView,
    ProspectListCreateView,
    ResponseRefinementView,
)

# Public intake endpoints (token-gated)
intake_patterns = [
    path("<uuid:token>/", IntakeSessionDetailView.as_view()),
    path("<uuid:token>/responses/", IntakeResponseSaveView.as_view()),
    path("<uuid:token>/submit/", IntakeSubmitView.as_view()),
]

# Internal staff endpoints
internal_patterns = [
    path("prospects/", ProspectListCreateView.as_view()),
    path("prospects/<slug:slug>/", ProspectDetailView.as_view()),
    path("prospects/<slug:slug>/sessions/", IntakeSessionCreateView.as_view()),
    path("prospects/<slug:slug>/sessions/<uuid:session_id>/", IntakeSessionDetailInternalView.as_view()),
    path(
        "prospects/<slug:slug>/sessions/<uuid:session_id>/responses/<uuid:response_id>/",
        ResponseRefinementView.as_view(),
    ),
    path("prospects/<slug:slug>/sessions/<uuid:session_id>/insights/", InsightCreateView.as_view()),
    path("prospects/<slug:slug>/notes/", NoteCreateView.as_view()),
]
