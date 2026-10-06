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
    path("storyboards/<uuid:storyboard_id>/items/<uuid:item_id>/surface", views.StoryboardSurfaceStateView.as_view(), name="storyboard-surface-state"),
    path("storyboards/<uuid:storyboard_id>/surface/reset", views.StoryboardResetLayoutView.as_view(), name="storyboard-reset-layout"),
    path("storyboards/<uuid:storyboard_id>/notes", views.StoryboardNoteListView.as_view(), name="storyboard-notes"),
    path("storyboards/<uuid:storyboard_id>/entities", views.StoryboardEntityListView.as_view(), name="storyboard-entities"),
    path("storyboards/<uuid:storyboard_id>/items/<uuid:item_id>/participations", views.StoryboardParticipationView.as_view(), name="storyboard-participation"),
    path("storyboards/<uuid:storyboard_id>/items/<uuid:item_id>/participations/<int:participation_id>", views.StoryboardParticipationDetailView.as_view(), name="storyboard-participation-detail"),
    path("storyboards/<uuid:storyboard_id>/items/<uuid:item_id>/links", views.StoryboardItemLinkView.as_view(), name="storyboard-item-link"),
    path("storyboards/<uuid:storyboard_id>/items/<uuid:item_id>/links/<int:link_id>", views.StoryboardItemLinkDetailView.as_view(), name="storyboard-item-link-detail"),
]
