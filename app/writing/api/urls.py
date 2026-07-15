# writing/api/urls.py


from django.urls import path

from .sponsor_views import (
    SponsorDraftDeleteView,
    SponsorDraftsListView,
    SponsorPlacementsListView,
)
from .leaf_views import (
    LeafDetailView,
    LeafImageUploadView,
    LeafListCreateView,
    LeafPromoteView,
    LeafPublishView,
    LeafReferenceCreateView,
    SeedToLeafPromoteView,
)
from .placement_views import (
    LeafPlacementCreateView,
    LeafPlacementDetailView,
    PlacementCommentDetailView,
    PlacementCommentListCreateView,
    PlacementReactionView,
)
from .run_views import (
    WritingRunListCreateView,
    WritingRunDetailView,
    WritingRunPublishView,
    WritingRunMembersView,
    WritingRunMemberDetailView,
    WritingRunMembersReorderView,
    WritingPieceSignOffView,
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
    WritingPieceAnalysisExportView,
    WritingPiecePdfExportView,
    WritingPieceImageUploadView,
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
    WritingPieceSuggestedRevisionCreateView,
    WritingPieceExecuteSplitView,
    WritingSeriesListView,
    WritingSynopsisView,
    WritingSynopsisRegenerateView,
    WritingSynopsisLinkedInCopyView,
    clear_empty_flag,
)


app_name = "writing"

# parent url # api/writing/

urlpatterns = [

    # Sponsor-based queries (generic for groups and members)
    # DEPRECATED: SponsorPlacementsListView — to be removed once frontend migrates to /api/storyline/
    path("placements", SponsorPlacementsListView.as_view(), name="sponsor-placements-list"),

    # LeafPlacement — Storyline social placements
    path("placements/create", LeafPlacementCreateView.as_view(), name="leaf-placement-create"),
    path("placements/<uuid:pk>", LeafPlacementDetailView.as_view(), name="leaf-placement-detail"),
    path("placements/<uuid:placement_id>/comments", PlacementCommentListCreateView.as_view(), name="placement-comments"),
    path("placements/<uuid:placement_id>/reactions", PlacementReactionView.as_view(), name="placement-reactions"),
    path("placement-comments/<uuid:pk>", PlacementCommentDetailView.as_view(), name="placement-comment-detail"),
    path("drafts", SponsorDraftsListView.as_view(), name="sponsor-drafts-list"),
    path("drafts/<uuid:pk>", SponsorDraftDeleteView.as_view(), name="sponsor-drafts-delete"),

    # Pieces
    path("pieces", WritingPieceListCreateView.as_view(), name="writingpiece-list-create"),
    path("pieces/<uuid:pk>", WritingPieceRetrieveUpdateDestroyView.as_view(), name="writingpiece-detail"),
    path("pieces/view/<slug:slug>", WritingPiecePublicView.as_view(), name="writingpiece-public-view"),
    path("pieces/<uuid:pk>/upload-image", WritingPieceImageUploadView.as_view(), name="writingpiece-upload-image"),

    # Working copy (autosave buffer)
    path("pieces/<uuid:pk>/working-copy", WorkingDocumentUpsertView.as_view(), name="writingpiece-working-document"),
    path("pieces/<uuid:pk>/apply-working-copy", WorkingDocumentApplyView.as_view(), name="writingpiece-apply-working-document"),
    path("pieces/<uuid:pk>/export/pdf", WritingPiecePdfExportView.as_view(), name="writingpiece-export-pdf"),
    path("pieces/<uuid:pk>/analysis/export", WritingPieceAnalysisExportView.as_view(), name="writingpiece-analysis-export"),
    path("pieces/<uuid:pk>/analysis/sessions/<uuid:session_id>/create-revision", WritingPieceSuggestedRevisionCreateView.as_view(), name="writingpiece-suggested-revision-create"),

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
    path("pieces/<uuid:pk>/synopsis/linkedin-copy", WritingSynopsisLinkedInCopyView.as_view(), name="writingpiece-synopsis-linkedin-copy"),

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
    # NOTE: leaf-scoped comments removed. Comments are now placement-scoped.
    # Use /api/writing/placements/<id>/comments instead.

    # Seed → Leaf promotion (Draftroom curation)
    path("seeds/<uuid:pk>/promote-to-leaf", SeedToLeafPromoteView.as_view(), name="seed-promote-to-leaf"),

    # Streams (chronological feed from followed users)
    path("streams", StreamsView.as_view(), name="streams"),

    # Writing Assembly — Runs (ADR-0054)
    path("runs", WritingRunListCreateView.as_view(), name="run-list-create"),
    path("runs/<uuid:run_id>", WritingRunDetailView.as_view(), name="run-detail"),
    path("runs/<uuid:run_id>/publish", WritingRunPublishView.as_view(), name="run-publish"),
    path("runs/<uuid:run_id>/members", WritingRunMembersView.as_view(), name="run-members"),
    path("runs/<uuid:run_id>/members/<uuid:piece_id>", WritingRunMemberDetailView.as_view(), name="run-member-detail"),
    path("runs/<uuid:run_id>/members/reorder", WritingRunMembersReorderView.as_view(), name="run-members-reorder"),

    # Sign-off toggle (ADR-0054 D10)
    path("pieces/<uuid:pk>/sign-off", WritingPieceSignOffView.as_view(), name="writingpiece-sign-off"),

]
