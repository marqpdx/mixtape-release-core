# writing/api/urls.py


from django.urls import path

from .sponsor_views import (
    SponsorDraftDeleteView,
    SponsorDraftsListView,
    SponsorPlacementsListView,
)
from .leaf_views import (
    LeafCommentDetailView,
    LeafCommentListCreateView,
    LeafDetailView,
    LeafImageUploadView,
    LeafListCreateView,
    LeafPromoteView,
    LeafPublishView,
    LeafReferenceCreateView,
    SeedToLeafPromoteView,
)
from .streams_views import StreamsView
from .views import (
    DocumentImportBatchConfirmView,
    DocumentImportBatchPreviewView,
    DocxImportView,
    DocxPreviewView,
    GroupWritingCatalogView,
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
    WritingPieceUnpublishView,
    WritingPieceUnpinView,
    WorkingDocumentApplyView,
    WorkingDocumentUpsertView,
    WritingPieceSplitSuggestionView,
    WritingPieceExecuteSplitView,
    WritingSeriesListView,
    WritingSynopsisView,
    WritingSynopsisRegenerateView,
    clear_empty_flag,
)


app_name = "writing"

# parent url # api/writing/

urlpatterns = [

    # Sponsor-based queries (generic for groups and members)
    path("placements", SponsorPlacementsListView.as_view(), name="sponsor-placements-list"),
    path("drafts", SponsorDraftsListView.as_view(), name="sponsor-drafts-list"),
    path("drafts/<uuid:pk>", SponsorDraftDeleteView.as_view(), name="sponsor-drafts-delete"),

    # Pieces
    path("pieces", WritingPieceListCreateView.as_view(), name="writingpiece-list-create"),
    path("pieces/<uuid:pk>", WritingPieceRetrieveUpdateDestroyView.as_view(), name="writingpiece-detail"),
    path("pieces/view/<slug:slug>", WritingPiecePublicView.as_view(), name="writingpiece-public-view"),

    # Working copy (autosave buffer)
    path("pieces/<uuid:pk>/working-copy", WorkingDocumentUpsertView.as_view(), name="writingpiece-working-document"),
    path("pieces/<uuid:pk>/apply-working-copy", WorkingDocumentApplyView.as_view(), name="writingpiece-apply-working-document"),

    # Split suggestion
    path("pieces/<uuid:pk>/split-suggestion", WritingPieceSplitSuggestionView.as_view(), name="writingpiece-split-suggestion"),

    # Split execution (Phase 4 — deterministic, no AI)
    path("pieces/<uuid:pk>/execute-split", WritingPieceExecuteSplitView.as_view(), name="writingpiece-execute-split"),

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

    # Series
    path("series", WritingSeriesListView.as_view(), name="writing-series-list"),

    # Catalog (published pieces for a group, grouped by series)
    path("catalog", GroupWritingCatalogView.as_view(), name="group-writing-catalog"),

    # Synopsis
    path("pieces/<uuid:pk>/synopsis", WritingSynopsisView.as_view(), name="writingpiece-synopsis"),
    path("pieces/<uuid:pk>/synopsis/regenerate", WritingSynopsisRegenerateView.as_view(), name="writingpiece-synopsis-regenerate"),

    # Publish & schedule
    path("pieces/<uuid:pk>/publish", WritingPiecePublishAndPlaceView.as_view(), name="writingpiece-publish"),
    path("pieces/<uuid:pk>/schedule", WritingPieceScheduleView.as_view(), name="writingpiece-schedule"),
    path("pieces/<uuid:pk>/unpublish", WritingPieceUnpublishView.as_view(), name="writingpiece-unpublish"),




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

    # DOCX Import
    path("import/preview", DocxPreviewView.as_view(), name="docx-preview"),
    path("import/confirm", DocxImportView.as_view(), name="docx-import"),
    path("import/preview-batch", DocumentImportBatchPreviewView.as_view(), name="document-import-preview-batch"),
    path("import/confirm-batch", DocumentImportBatchConfirmView.as_view(), name="document-import-confirm-batch"),

    # Leaves (Storyline)
    path("leaves", LeafListCreateView.as_view(), name="leaf-list-create"),
    path("leaves/reference", LeafReferenceCreateView.as_view(), name="leaf-reference-create"),
    path("leaves/upload-image", LeafImageUploadView.as_view(), name="leaf-image-upload"),
    path("leaves/<uuid:pk>", LeafDetailView.as_view(), name="leaf-detail"),
    path("leaves/<uuid:pk>/promote", LeafPromoteView.as_view(), name="leaf-promote"),
    path("leaves/<uuid:pk>/publish", LeafPublishView.as_view(), name="leaf-publish"),
    path("leaves/<uuid:leaf_id>/comments", LeafCommentListCreateView.as_view(), name="leaf-comments"),

    # Leaf Comments
    path("comments/<uuid:pk>", LeafCommentDetailView.as_view(), name="leaf-comment-detail"),

    # Seed → Leaf promotion (Draftroom curation)
    path("seeds/<uuid:pk>/promote-to-leaf", SeedToLeafPromoteView.as_view(), name="seed-promote-to-leaf"),

    # Streams (chronological feed from followed users)
    path("streams", StreamsView.as_view(), name="streams"),

]
