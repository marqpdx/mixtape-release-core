from django.urls import path

from .views import (
    CategoryView,
    ReadinessView,
    TagDeleteView,
    TagListCreateView,
    TagSearchView,
)

urlpatterns = [
    # Tag search must precede <slug:piece_slug>/ patterns
    path("tags/search/", TagSearchView.as_view()),

    path("<slug:piece_slug>/readiness/", ReadinessView.as_view()),
    path("<slug:piece_slug>/tags/", TagListCreateView.as_view()),
    path("<slug:piece_slug>/tags/<uuid:cu_id>/", TagDeleteView.as_view()),
    path("<slug:piece_slug>/category/", CategoryView.as_view()),
]
