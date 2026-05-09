from django.urls import path

from .views import (
    HubCaptureDetailView,
    HubCaptureListCreateView,
    HubCapturePromoteView,
    HubCaptureVoiceView,
    OrientationView,
    ReentryView,
    SignalsView,
    StewardshipView,
    WorkTableStreamView,
)

urlpatterns = [
    path("reentry/", ReentryView.as_view(), name="console-reentry"),
    path("signals/", SignalsView.as_view(), name="console-signals"),
    path("orientation/", OrientationView.as_view(), name="console-orientation"),
    path("stewardship/", StewardshipView.as_view(), name="console-stewardship"),
    # HubCapture
    path("hub/captures/", HubCaptureListCreateView.as_view(), name="hub-capture-list"),
    path("hub/captures/<uuid:capture_id>/", HubCaptureDetailView.as_view(), name="hub-capture-detail"),
    path("hub/captures/promote/", HubCapturePromoteView.as_view(), name="hub-capture-promote"),
    path("hub/captures/voice/", HubCaptureVoiceView.as_view(), name="hub-capture-voice"),
]
