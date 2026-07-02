from django.urls import path

from media_capture.views import MediaCaptureDetailView, MediaCaptureUploadView

urlpatterns = [
    path("upload/", MediaCaptureUploadView.as_view(), name="media-capture-upload"),
    path("<uuid:capture_id>/", MediaCaptureDetailView.as_view(), name="media-capture-detail"),
]
