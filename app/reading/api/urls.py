from django.urls import path

from .views import (
    DartDetailView,
    DartListCreateView,
    ReadingStatsFlagView,
    ReadingStatsRecordView,
    ReadingStatsView,
)

urlpatterns = [
    path("darts/", DartListCreateView.as_view()),
    path("darts/<uuid:dart_id>/", DartDetailView.as_view()),
    path("stats/<uuid:artifact_id>/", ReadingStatsView.as_view()),
    path("stats/<uuid:artifact_id>/record/", ReadingStatsRecordView.as_view()),
    path("stats/<uuid:artifact_id>/flag/", ReadingStatsFlagView.as_view()),
]
