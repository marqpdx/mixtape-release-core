# storyboard/api/urls.py
# No trailing slashes -- follows project convention (see folio/api/urls.py).

from django.urls import path

from . import views

urlpatterns = [
    path("storyboards", views.StoryboardListCreateView.as_view(), name="storyboard-list-create"),
    path(
        "storyboards/<uuid:storyboard_id>",
        views.StoryboardDetailView.as_view(),
        name="storyboard-detail",
    ),
    path(
        "storyboards/<uuid:storyboard_id>/items",
        views.StoryboardItemListCreateView.as_view(),
        name="storyboard-item-list-create",
    ),
    path(
        "storyboards/<uuid:storyboard_id>/items/<uuid:item_id>",
        views.StoryboardItemDetailView.as_view(),
        name="storyboard-item-detail",
    ),
    path(
        "storyboards/<uuid:storyboard_id>/items/reorder",
        views.StoryboardReorderView.as_view(),
        name="storyboard-item-reorder",
    ),
]
