# stackroom/api/urls.py

from django.urls import path
from stackroom.api.views import (
    IngestionStartView,
    ArtifactCreateView,
    ShardBulkUpsertView,
    ChunkBulkUpsertView,
    IngestionCompleteView,
    RetrieveView,
    HealthCheckView,
    ArtifactContentView,
    SourceFileContentView,
    FileUploadView,
    LibraryListCreateView,
    LibraryDetailView,
    PublicLibraryListView,
    LibraryPlacementsView,
    LibraryPlacementsManageView,
    LibraryPlacementsReorderView,
)
from stackroom.api.activity_views import LibraryActivityView
from stackroom.api.puddlejump_views import (
    PuddlejumpImportView,
    PuddlejumpHealthView,
    PuddlejumpAuthDebugView,
    PersonalPuddlejumpView,
    PuddlejumpSyncStatusView,
    PuddlejumpSyncUploadView,
    PuddlejumpSyncDownloadView,
    PuddlejumpSyncDeleteView,
    PuddlejumpSyncCompleteView,
)
from stackroom.api.puddlejump_utility_views import (
    LibraryHealthView,
    DuplicateDetectionView,
    GlossaryExtractionView,
    CanonicalCandidatesView,
    SuggestSummariesView,
    RestructureView,
)

urlpatterns = [
    path("health", HealthCheckView.as_view(), name="stackroom-health"),
    path("libraries", LibraryListCreateView.as_view(), name="library-list"),
    path("libraries/public", PublicLibraryListView.as_view(), name="library-public-list"),
    path("libraries/<uuid:library_id>", LibraryDetailView.as_view(), name="library-detail"),
    path("libraries/<uuid:library_id>/placements", LibraryPlacementsView.as_view(), name="library-placements"),
    path("libraries/<uuid:library_id>/placements/manage", LibraryPlacementsManageView.as_view(), name="library-placements-manage"),
    path("libraries/<uuid:library_id>/placements/reorder", LibraryPlacementsReorderView.as_view(), name="library-placements-reorder"),
    path(
        "libraries/<uuid:library_id>/placements/<uuid:placement_id>",
        LibraryPlacementsManageView.as_view(),
        name="library-placements-delete",
    ),
    path("libraries/<uuid:library_id>/activity", LibraryActivityView.as_view(), name="library-activity"),
    path("upload", FileUploadView.as_view(), name="file-upload"),
    path("ingestion/start", IngestionStartView.as_view()),
    path("artifacts", ArtifactCreateView.as_view()),
    path("artifacts/<uuid:artifact_id>/content", ArtifactContentView.as_view(), name="artifact-content"),
    path("source-files/<uuid:source_file_id>/content", SourceFileContentView.as_view(), name="source-file-content"),
    path("shards/bulk", ShardBulkUpsertView.as_view()),
    path("chunks/bulk", ChunkBulkUpsertView.as_view()),
    path("ingestion/complete", IngestionCompleteView.as_view()),
    path("retrieve", RetrieveView.as_view()),
    # Puddlejump endpoints
    path("puddlejump/health", PuddlejumpHealthView.as_view(), name="puddlejump-health"),
    path("puddlejump/auth-debug", PuddlejumpAuthDebugView.as_view(), name="puddlejump-auth-debug"),
    path("puddlejump/personal", PersonalPuddlejumpView.as_view(), name="puddlejump-personal"),
    path("puddlejump/import", PuddlejumpImportView.as_view(), name="puddlejump-import"),
    # Puddlejump sync endpoints (for desktop client)
    path("puddlejump/sync/status", PuddlejumpSyncStatusView.as_view(), name="puddlejump-sync-status"),
    path("puddlejump/sync/upload", PuddlejumpSyncUploadView.as_view(), name="puddlejump-sync-upload"),
    path("puddlejump/sync/download/<uuid:file_id>", PuddlejumpSyncDownloadView.as_view(), name="puddlejump-sync-download"),
    path("puddlejump/sync/delete/<uuid:file_id>", PuddlejumpSyncDeleteView.as_view(), name="puddlejump-sync-delete"),
    path("puddlejump/sync/complete", PuddlejumpSyncCompleteView.as_view(), name="puddlejump-sync-complete"),
    # Puddlejump utility endpoints
    path("puddlejump/utilities/libraries/<uuid:library_id>/health", LibraryHealthView.as_view(), name="puddlejump-library-health"),
    path("puddlejump/utilities/check-duplicates", DuplicateDetectionView.as_view(), name="puddlejump-check-duplicates"),
    path("puddlejump/utilities/extract-glossary", GlossaryExtractionView.as_view(), name="puddlejump-extract-glossary"),
    path("puddlejump/utilities/suggest-canonical", CanonicalCandidatesView.as_view(), name="puddlejump-suggest-canonical"),
    path("puddlejump/utilities/suggest-summaries", SuggestSummariesView.as_view(), name="puddlejump-suggest-summaries"),
    path("puddlejump/utilities/restructure", RestructureView.as_view(), name="puddlejump-restructure"),
]
