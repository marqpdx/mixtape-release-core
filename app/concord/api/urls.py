# concord/api/urls.py
# ============================================================================
# Concord API URLs
# ============================================================================

from django.urls import path
from . import views

app_name = 'concord'

urlpatterns = [
    # ========================================================================
    # Recording Endpoints
    # ========================================================================
    path('recordings/', views.recording_list_create, name='recording-list-create'),
    path('recordings/<uuid:recording_id>/', views.recording_detail, name='recording-detail'),
    path('recordings/<uuid:recording_id>/upload/', views.recording_upload, name='recording-upload'),
    path('recordings/<uuid:recording_id>/transition/', views.recording_transition, name='recording-transition'),
    path('recordings/<uuid:recording_id>/transcriptions/', views.recording_transcriptions, name='recording-transcriptions'),
    path('recordings/<uuid:recording_id>/transcribe/', views.trigger_transcription, name='recording-transcribe'),

    # ========================================================================
    # RecordingSession Endpoints
    # ========================================================================
    path('sessions/', views.session_list_create, name='session-list-create'),
    path('sessions/<uuid:session_id>/', views.session_detail, name='session-detail'),
    path('sessions/<uuid:session_id>/anchors/', views.session_anchors, name='session-anchors'),

    # ========================================================================
    # SpeakerAnchor Endpoints
    # ========================================================================
    path('anchors/', views.anchor_list_create, name='anchor-list-create'),
    path('anchors/<uuid:anchor_id>/', views.anchor_detail, name='anchor-detail'),

    # ========================================================================
    # Transcription Endpoints (Read-Only)
    # ========================================================================
    path('transcriptions/', views.transcription_list, name='transcription-list'),
    path('transcriptions/<uuid:transcription_id>/', views.transcription_detail, name='transcription-detail'),

    # ========================================================================
    # Group-specific Convenience Endpoints
    # ========================================================================
    path('groups/<slug:group_slug>/recordings/', views.group_recordings, name='group-recordings'),
    path('groups/<slug:group_slug>/recordings/create/', views.group_recording_create, name='group-recording-create'),
    path('groups/<slug:group_slug>/sessions/', views.group_sessions, name='group-sessions'),
    path('groups/<slug:group_slug>/sessions/create/', views.group_session_create, name='group-session-create'),
    path('groups/<slug:group_slug>/sessions/bulk-upload/', views.group_sessions_bulk_upload, name='group-sessions-bulk-upload'),
    path('groups/<slug:group_slug>/upload/', views.group_upload, name='group-upload'),
]
