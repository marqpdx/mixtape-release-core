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
)
from stackroom.api.activity_views import LibraryActivityView
from stackroom.api.puddlejump_views import (
    PuddlejumpImportView,
    PuddlejumpHealthView,
    PersonalPuddlejumpView,
    PuddlejumpSyncStatusView,
    PuddlejumpSyncUploadView,
    PuddlejumpSyncDownloadView,
    PuddlejumpSyncDeleteView,
    PuddlejumpSyncCompleteView,
)

urlpatterns = [
    path("health", HealthCheckView.as_view(), name="stackroom-health"),
    path("libraries", LibraryListCreateView.as_view(), name="library-list"),
    path("libraries/<uuid:library_id>", LibraryDetailView.as_view(), name="library-detail"),
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
    path("puddlejump/personal", PersonalPuddlejumpView.as_view(), name="puddlejump-personal"),
    path("puddlejump/import", PuddlejumpImportView.as_view(), name="puddlejump-import"),
    # Puddlejump sync endpoints (for desktop client)
    path("puddlejump/sync/status", PuddlejumpSyncStatusView.as_view(), name="puddlejump-sync-status"),
    path("puddlejump/sync/upload", PuddlejumpSyncUploadView.as_view(), name="puddlejump-sync-upload"),
    path("puddlejump/sync/download/<uuid:file_id>", PuddlejumpSyncDownloadView.as_view(), name="puddlejump-sync-download"),
    path("puddlejump/sync/delete/<uuid:file_id>", PuddlejumpSyncDeleteView.as_view(), name="puddlejump-sync-delete"),
    path("puddlejump/sync/complete", PuddlejumpSyncCompleteView.as_view(), name="puddlejump-sync-complete"),
]
