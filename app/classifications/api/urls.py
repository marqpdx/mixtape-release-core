from django.urls import path

from classifications.api.views import (
    CategoryListCreateView,
    CategoryRetrieveUpdateDestroyView,
    TagListCreateView,
    TagRetrieveUpdateDestroyView,
)


urlpatterns = [
    path("tags", TagListCreateView.as_view(), name="tag-list"),
    path("tags/<slug:slug>", TagRetrieveUpdateDestroyView.as_view(), name="tag-detail"),
    path("categories", CategoryListCreateView.as_view(), name="category-list"),
    path(
        "categories/<slug:slug>",
        CategoryRetrieveUpdateDestroyView.as_view(),
        name="category-detail",
    ),
]
