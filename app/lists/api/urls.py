from django.urls import path

from lists.api.views import (
    ListBySlugView,
    ListDetailView,
    ListItemToggleView,
    ListReorderView,
    ListRootView,
    ListSearchView,
)


app_name = "lists"

urlpatterns = [
    # GET: list user's lists, POST: create new list
    path("", ListRootView.as_view(), name="list-root"),

    # Search lists by title/slug
    path("search/", ListSearchView.as_view(), name="list-search"),

    # Get list by slug (for /list <query> command)
    path("by-slug/<slug:slug>/", ListBySlugView.as_view(), name="list-by-slug"),

    # CRUD by ID
    path("<uuid:list_id>/", ListDetailView.as_view(), name="list-detail"),

    # Item operations
    path("<uuid:list_id>/items/<int:item_index>/toggle", ListItemToggleView.as_view(), name="list-item-toggle"),
    path("<uuid:list_id>/reorder", ListReorderView.as_view(), name="list-reorder"),
]
