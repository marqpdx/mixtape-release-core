# api/writing/urls.py


from django.urls import path

from .sponsor_views import (
    SponsorDraftsListView,
    SponsorPlacementsListView,
)
from .views import (
    SeedDetailView,
    SeedIngestView,
    SeedListCreateView,
    SeedPromoteView,
    WorkingDocumentCollaborationStatusView,
    WorkingDocumentEligibleCollaboratorsView,
    WorkingDocumentEnableCollaborationView,
    WorkingDocumentRescindCollaborationView,
    WritingCommentListCreateView,
    WritingPieceCategoriesView,
    WritingPieceListCreateView,
    WritingPiecePinView,
    WritingPiecePublicView,
    WritingPiecePublishAndPlaceView,
    WritingPieceRetrieveUpdateDestroyView,
    WritingPieceScheduleView,
    WritingPieceTagsView,
    WritingPieceUnpinView,
    WritingWorkingCopyApplyView,
    WritingWorkingCopyUpsertView,
    clear_empty_flag,
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
    path("pieces/view/<slug:slug>", WritingPiecePublicView.as_view(), name="writingpiece-public-view"),

    # Working copy (autosave buffer)
    path("pieces/<uuid:pk>/working-copy", WritingWorkingCopyUpsertView.as_view(), name="writingpiece-workingcopy"),
    path("pieces/<uuid:pk>/apply-working-copy", WritingWorkingCopyApplyView.as_view(), name="writingpiece-apply-workingcopy"),

    # Collaboration management (on working documents)
    path("working-documents/<uuid:piece_id>/collaboration/status", WorkingDocumentCollaborationStatusView.as_view(),
        name="workingdocument-collaboration-status"),
    path("working-documents/<uuid:piece_id>/collaboration/eligible", WorkingDocumentEligibleCollaboratorsView.as_view(),
        name="workingdocument-eligible-collaborators"),
    path("working-documents/<uuid:piece_id>/collaboration/enable", WorkingDocumentEnableCollaborationView.as_view(),
        name="workingdocument-enable-collaboration"),
    path("working-documents/<uuid:piece_id>/collaboration/rescind", WorkingDocumentRescindCollaborationView.as_view(),
        name="workingdocument-rescind-collaboration"),

    # Clear empty flag
    path("pieces/<uuid:piece_id>/clear-empty", clear_empty_flag, name="clear-empty-flag"),

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

    # Tags and Categories
    path("pieces/<uuid:pk>/tags", WritingPieceTagsView.as_view(), name="writingpiece-tags"),
    path("pieces/<uuid:pk>/categories", WritingPieceCategoriesView.as_view(), name="writingpiece-categories"),

]
