# api/writing/urls.py


from django.urls import path
from .views import (
    SeedDetailView,
    SeedIngestView,
    SeedListCreateView,
    SeedPromoteView,
    WritingCommentListCreateView,
    WritingPieceListCreateView,
    WritingPiecePublishAndPlaceView,
    WritingPieceRetrieveUpdateDestroyView,
    WritingWorkingCopyUpsertView,
    WritingWorkingCopyApplyView,
    WritingPieceScheduleView,
    WritingPiecePinView,
    WritingPieceUnpinView,
    clear_empty_flag,
)
from .sponsor_views import (
    SponsorPlacementsListView,
    SponsorDraftsListView,
)

app_name = "writing"

# parent url # api/writing/

urlpatterns = [

    # Sponsor-based queries (generic for groups and members)
    path("placements", SponsorPlacementsListView.as_view(), name="sponsor-placements-list"),
    path("drafts", SponsorDraftsListView.as_view(), name="sponsor-drafts-list"),

    # Pieces
    path("pieces", WritingPieceListCreateView.as_view(), name="writingpiece-list-create"),
    path("pieces/<uuid:pk>", WritingPieceRetrieveUpdateDestroyView.as_view(), name="writingpiece-detail"),

    # Working copy (autosave buffer)
    path("pieces/<uuid:pk>/working-copy", WritingWorkingCopyUpsertView.as_view(), name="writingpiece-workingcopy"),
    path("pieces/<uuid:pk>/apply-working-copy", WritingWorkingCopyApplyView.as_view(), name="writingpiece-apply-workingcopy"),

    # Clear empty flag
    path("pieces/<uuid:piece_id>/clear-empty", clear_empty_flag, name='clear-empty-flag'),

    # Publish & schedule
    path("pieces/<uuid:pk>/publish", WritingPiecePublishAndPlaceView.as_view(), name="writingpiece-publish"),
    path("pieces/<uuid:pk>/schedule", WritingPieceScheduleView.as_view(), name="writingpiece-schedule"),




    # URL pattern
    path("groups/<slug:group_slug>/writing/<uuid:piece_id>/comments/",
        WritingCommentListCreateView.as_view(), name="writing-comments"),


    # Pinning
    path("pieces/<uuid:pk>/pin", WritingPiecePinView.as_view(), name="writingpiece-pin"),
    path("pieces/<uuid:pk>/unpin", WritingPieceUnpinView.as_view(), name="writingpiece-unpin"),

    # Seeds
    path("seeds", SeedListCreateView.as_view(), name="seed-list-create"),
    path("seeds/ingest", SeedIngestView.as_view(), name="seed-ingest"),
    path("seeds/<uuid:pk>", SeedDetailView.as_view(), name="seed-detail"),
    path("seeds/<uuid:pk>/promote", SeedPromoteView.as_view(), name="seed-promote"),

]
