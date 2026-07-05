from django.urls import path

from media_capture.views import (
    MediaCaptureDetailView,
    MediaCaptureListView,
    MediaCaptureStreamView,
    MediaCaptureUploadView,
)

urlpatterns = [
    path("", MediaCaptureListView.as_view(), name="media-capture-list"),
    path("upload", MediaCaptureUploadView.as_view(), name="media-capture-upload"),
    path("<uuid:capture_id>", MediaCaptureDetailView.as_view(), name="media-capture-detail"),
    path("<uuid:capture_id>/stream", MediaCaptureStreamView.as_view(), name="media-capture-stream"),
]
