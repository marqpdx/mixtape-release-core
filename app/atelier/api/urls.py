from django.urls import path

from .views import (
    CategoryView,
    ReadinessView,
    SeriesSearchView,
    SeriesView,
    SummariesConfirmView,
    SummariesView,
    TagDeleteView,
    TagListCreateView,
    TagSearchView,
)

urlpatterns = [
    # Fixed paths must precede <slug:piece_slug>/ patterns
    path("tags/search/", TagSearchView.as_view()),

    path("<slug:piece_slug>/readiness/", ReadinessView.as_view()),
    path("<slug:piece_slug>/tags/", TagListCreateView.as_view()),
    path("<slug:piece_slug>/tags/<uuid:cu_id>/", TagDeleteView.as_view()),
    path("<slug:piece_slug>/category/", CategoryView.as_view()),
    path("<slug:piece_slug>/summaries/", SummariesView.as_view()),
    path("<slug:piece_slug>/summaries/confirm/", SummariesConfirmView.as_view()),
    path("<slug:piece_slug>/series/", SeriesView.as_view()),
    path("<slug:piece_slug>/series/search/", SeriesSearchView.as_view()),
]
