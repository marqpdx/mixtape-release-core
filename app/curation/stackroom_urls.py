from django.urls import path

from curation.api.stackroom_proxy_views import (
    StackroomSourceFileDownloadProxyView,
    StackroomSourceFileReadableProxyView,
)

urlpatterns = [
    path(
        "source-files/<uuid:source_file_id>/readable",
        StackroomSourceFileReadableProxyView.as_view(),
        name="stackroom-source-file-readable",
    ),
    path(
        "source-files/<uuid:source_file_id>/download",
        StackroomSourceFileDownloadProxyView.as_view(),
        name="stackroom-source-file-download",
    ),
]
