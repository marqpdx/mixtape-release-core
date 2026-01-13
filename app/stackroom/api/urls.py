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
    path("puddlejump/import/", PuddlejumpImportView.as_view(), name="puddlejump-import"),
]
