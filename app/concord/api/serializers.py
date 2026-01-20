# concord/api/serializers.py
# ============================================================================
# Concord API Serializers
#
# Models inherit from BaseContent, providing:
# - title, slug, summary, body (content fields)
# - sponsor (polymorphic GenericFK)
# - author, author_name, submitted_by (authorship)
# - tags, categories, published_at
# ============================================================================

from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from concord.models import (
    Recording,
    RecordingStatus,
    RecordingSession,
    SessionStatus,
    SpeakerAnchor,
    Transcription,
    TranscriptSegment,
    TrackType,
)


class RecordingSerializer(serializers.Serializer):
    """
    Read serializer for Recording model.
    Used for list and detail views.
    """
    id = serializers.UUIDField(read_only=True)

    # BaseContent fields
    title = serializers.CharField()
    slug = serializers.CharField(read_only=True)
    summary = serializers.CharField()
    body = serializers.CharField()  # Detailed notes/description

    # Sponsor info (from BaseContent)
    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()

    # Authorship (from BaseContent)
    author_id = serializers.SerializerMethodField()
    author_name = serializers.CharField()
    submitted_by_id = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()

    # Audio metadata
    duration_ms = serializers.IntegerField(allow_null=True)
    duration_formatted = serializers.CharField(read_only=True)
    recorded_at = serializers.DateTimeField(allow_null=True)

    # Status
    status = serializers.ChoiceField(choices=RecordingStatus.choices)
    status_changed_at = serializers.DateTimeField(read_only=True)

    # Storage
    audio_url = serializers.CharField(read_only=True, allow_null=True)
    audio_content_type = serializers.CharField()
    audio_size_bytes = serializers.IntegerField(allow_null=True)

    # Timestamps
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    published_at = serializers.DateTimeField(read_only=True, allow_null=True)

    # Processing
    processing_started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    processing_completed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    processing_error = serializers.CharField(read_only=True)

    def get_sponsor_type(self, obj):
        return obj.sponsor_content_type.model

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_author_id(self, obj):
        if obj.author:
            return str(obj.author.id)
        return None

    def get_submitted_by_id(self, obj):
        if obj.submitted_by:
            return str(obj.submitted_by.id)
        return None

    def get_submitted_by_name(self, obj):
        if obj.submitted_by:
            return obj.submitted_by.get_full_name() or obj.submitted_by.username
        return None


class RecordingCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new Recording.
    Handles file upload and sponsor assignment.
    """
    # Sponsor context
    sponsor_type = serializers.ChoiceField(
        choices=['group', 'user'],
        help_text="Type of sponsor: 'group' or 'user'"
    )
    sponsor_id = serializers.UUIDField(
        help_text="UUID of the sponsoring group or user"
    )

    # BaseContent metadata
    title = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default=""
    )
    summary = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Short description of the recording"
    )
    body = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Detailed notes about the recording"
    )

    # Recording-specific
    recorded_at = serializers.DateTimeField(
        required=False,
        allow_null=True
    )

    # File upload (optional - can also be set separately)
    file = serializers.FileField(
        required=False,
        help_text="Audio file to upload"
    )

    def validate(self, attrs):
        """Validate sponsor exists"""
        sponsor_type = attrs.get('sponsor_type')
        sponsor_id = attrs.get('sponsor_id')

        if sponsor_type == 'group':
            from groups.models import Group
            try:
                Group.objects.get(id=sponsor_id)
            except Group.DoesNotExist:
                raise serializers.ValidationError({
                    'sponsor_id': f"Group with id '{sponsor_id}' does not exist"
                })
        elif sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                User.objects.get(id=sponsor_id)
            except User.DoesNotExist:
                raise serializers.ValidationError({
                    'sponsor_id': f"User with id '{sponsor_id}' does not exist"
                })

        return attrs


class RecordingUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating Recording metadata.
    """
    title = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True
    )
    summary = serializers.CharField(
        required=False,
        allow_blank=True
    )
    body = serializers.CharField(
        required=False,
        allow_blank=True
    )
    recorded_at = serializers.DateTimeField(
        required=False,
        allow_null=True
    )


class RecordingUploadSerializer(serializers.Serializer):
    """
    Serializer for uploading audio file to existing recording.
    """
    file = serializers.FileField(
        help_text="Audio file to upload"
    )

    def validate_file(self, file):
        """Validate file is audio"""
        allowed_types = [
            'audio/mpeg',
            'audio/mp3',
            'audio/wav',
            'audio/x-wav',
            'audio/m4a',
            'audio/mp4',
            'audio/x-m4a',
            'audio/aac',
            'audio/ogg',
            'audio/webm',
        ]

        content_type = file.content_type
        if content_type not in allowed_types:
            raise serializers.ValidationError(
                f"Unsupported audio format: {content_type}. "
                f"Supported formats: MP3, WAV, M4A, AAC, OGG, WebM"
            )

        # Check file size (max 500MB)
        max_size = 500 * 1024 * 1024  # 500MB
        if file.size > max_size:
            raise serializers.ValidationError(
                f"File too large. Maximum size is 500MB, got {file.size / (1024*1024):.1f}MB"
            )

        return file


class RecordingListSerializer(serializers.Serializer):
    """
    Lightweight serializer for listing recordings.
    """
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField()
    slug = serializers.CharField(read_only=True)
    summary = serializers.CharField()
    status = serializers.CharField()
    duration_formatted = serializers.CharField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    submitted_by_name = serializers.SerializerMethodField()

    # Session fields
    session_id = serializers.SerializerMethodField()
    segment_index = serializers.IntegerField(allow_null=True)
    track_type = serializers.CharField()

    def get_submitted_by_name(self, obj):
        if obj.submitted_by:
            return obj.submitted_by.get_full_name() or obj.submitted_by.username
        return None

    def get_session_id(self, obj):
        if obj.session:
            return str(obj.session.id)
        return None


# ============================================================================
# RecordingSession Serializers
# ============================================================================

class RecordingSessionSerializer(serializers.Serializer):
    """
    Read serializer for RecordingSession model.
    """
    id = serializers.UUIDField(read_only=True)

    # BaseContent fields
    title = serializers.CharField()
    slug = serializers.CharField(read_only=True)
    summary = serializers.CharField()
    body = serializers.CharField()

    # Sponsor info
    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()

    # Authorship
    submitted_by_id = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()

    # Session-specific
    external_call_id = serializers.CharField()
    session_started_at = serializers.DateTimeField(allow_null=True)
    session_ended_at = serializers.DateTimeField(allow_null=True)
    segment_duration_seconds = serializers.IntegerField()
    expected_participants = serializers.JSONField()
    status = serializers.ChoiceField(choices=SessionStatus.choices)

    # Computed
    segment_count = serializers.IntegerField(read_only=True)
    total_duration_ms = serializers.IntegerField(read_only=True)

    # Timestamps
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def get_sponsor_type(self, obj):
        return obj.sponsor_content_type.model

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_submitted_by_id(self, obj):
        if obj.submitted_by:
            return str(obj.submitted_by.id)
        return None

    def get_submitted_by_name(self, obj):
        if obj.submitted_by:
            return obj.submitted_by.get_full_name() or obj.submitted_by.username
        return None


class RecordingSessionCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new RecordingSession.
    """
    # Sponsor context
    sponsor_type = serializers.ChoiceField(choices=['group', 'user'])
    sponsor_id = serializers.UUIDField()

    # BaseContent metadata
    title = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField(required=False, allow_blank=True, default="")

    # Session-specific
    external_call_id = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    session_started_at = serializers.DateTimeField(required=False, allow_null=True)
    segment_duration_seconds = serializers.IntegerField(required=False, default=900)
    expected_participants = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )

    def validate(self, attrs):
        """Validate sponsor exists"""
        sponsor_type = attrs.get('sponsor_type')
        sponsor_id = attrs.get('sponsor_id')

        if sponsor_type == 'group':
            from groups.models import Group
            try:
                Group.objects.get(id=sponsor_id)
            except Group.DoesNotExist:
                raise serializers.ValidationError({
                    'sponsor_id': f"Group with id '{sponsor_id}' does not exist"
                })
        elif sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                User.objects.get(id=sponsor_id)
            except User.DoesNotExist:
                raise serializers.ValidationError({
                    'sponsor_id': f"User with id '{sponsor_id}' does not exist"
                })

        return attrs


class RecordingSessionUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating RecordingSession.
    """
    title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    summary = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    external_call_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    session_started_at = serializers.DateTimeField(required=False, allow_null=True)
    session_ended_at = serializers.DateTimeField(required=False, allow_null=True)
    expected_participants = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    status = serializers.ChoiceField(choices=SessionStatus.choices, required=False)


class RecordingSessionListSerializer(serializers.Serializer):
    """
    Lightweight serializer for listing sessions.
    """
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField()
    slug = serializers.CharField(read_only=True)
    status = serializers.CharField()
    segment_count = serializers.IntegerField(read_only=True)
    total_duration_ms = serializers.IntegerField(read_only=True)
    session_started_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    submitted_by_name = serializers.SerializerMethodField()

    def get_submitted_by_name(self, obj):
        if obj.submitted_by:
            return obj.submitted_by.get_full_name() or obj.submitted_by.username
        return None


# ============================================================================
# SpeakerAnchor Serializers
# ============================================================================

class SpeakerAnchorSerializer(serializers.Serializer):
    """
    Read serializer for SpeakerAnchor model.
    """
    id = serializers.UUIDField(read_only=True)

    # Scope
    session_id = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()

    # Identity
    speaker_label = serializers.CharField()
    user_id = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    # Voice sample reference
    source_recording_id = serializers.SerializerMethodField()
    sample_start_ms = serializers.IntegerField(allow_null=True)
    sample_end_ms = serializers.IntegerField(allow_null=True)

    # Embedding info (not the actual bytes)
    has_embedding = serializers.SerializerMethodField()
    embedding_model = serializers.CharField()

    # Confidence & status
    confidence_score = serializers.FloatField(allow_null=True)
    is_active = serializers.BooleanField()

    # Timestamps
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def get_session_id(self, obj):
        if obj.session:
            return str(obj.session.id)
        return None

    def get_group_id(self, obj):
        if obj.group:
            return str(obj.group.id)
        return None

    def get_user_id(self, obj):
        if obj.user:
            return str(obj.user.id)
        return None

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return None

    def get_source_recording_id(self, obj):
        if obj.source_recording:
            return str(obj.source_recording.id)
        return None

    def get_has_embedding(self, obj):
        return obj.embedding is not None and len(obj.embedding) > 0


class SpeakerAnchorCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a SpeakerAnchor.
    """
    # Scope (at least one required)
    session_id = serializers.UUIDField(required=False, allow_null=True)
    group_id = serializers.UUIDField(required=False, allow_null=True)

    # Identity
    speaker_label = serializers.CharField(max_length=100)
    user_id = serializers.UUIDField(required=False, allow_null=True)

    # Voice sample reference
    source_recording_id = serializers.UUIDField(required=False, allow_null=True)
    sample_start_ms = serializers.IntegerField(required=False, allow_null=True)
    sample_end_ms = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        """Validate at least one scope is provided"""
        session_id = attrs.get('session_id')
        group_id = attrs.get('group_id')

        if not session_id and not group_id:
            raise serializers.ValidationError(
                "At least one of 'session_id' or 'group_id' is required"
            )

        # Validate session exists
        if session_id:
            try:
                RecordingSession.objects.get(id=session_id)
            except RecordingSession.DoesNotExist:
                raise serializers.ValidationError({
                    'session_id': f"Session with id '{session_id}' does not exist"
                })

        # Validate group exists
        if group_id:
            from groups.models import Group
            try:
                Group.objects.get(id=group_id)
            except Group.DoesNotExist:
                raise serializers.ValidationError({
                    'group_id': f"Group with id '{group_id}' does not exist"
                })

        # Validate user exists
        user_id = attrs.get('user_id')
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise serializers.ValidationError({
                    'user_id': f"User with id '{user_id}' does not exist"
                })

        # Validate source recording exists
        source_recording_id = attrs.get('source_recording_id')
        if source_recording_id:
            try:
                Recording.objects.get(id=source_recording_id)
            except Recording.DoesNotExist:
                raise serializers.ValidationError({
                    'source_recording_id': f"Recording with id '{source_recording_id}' does not exist"
                })

        return attrs


class SpeakerAnchorUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating SpeakerAnchor.
    """
    speaker_label = serializers.CharField(max_length=100, required=False)
    user_id = serializers.UUIDField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    confidence_score = serializers.FloatField(required=False, allow_null=True)


class SpeakerAnchorListSerializer(serializers.Serializer):
    """
    Lightweight serializer for listing anchors.
    """
    id = serializers.UUIDField(read_only=True)
    speaker_label = serializers.CharField()
    user_name = serializers.SerializerMethodField()
    has_embedding = serializers.SerializerMethodField()
    confidence_score = serializers.FloatField(allow_null=True)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField(read_only=True)

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return None

    def get_has_embedding(self, obj):
        return obj.embedding is not None and len(obj.embedding) > 0


# ============================================================================
# Transcription Serializers (Read-Only)
# ============================================================================

class TranscriptSegmentSerializer(serializers.Serializer):
    """
    Read serializer for TranscriptSegment.
    """
    id = serializers.UUIDField(read_only=True)
    segment_index = serializers.IntegerField()
    start_ms = serializers.IntegerField()
    end_ms = serializers.IntegerField()
    duration_ms = serializers.IntegerField(read_only=True)
    text = serializers.CharField()

    # Speaker attribution
    speaker_anchor_id = serializers.SerializerMethodField()
    speaker_label = serializers.CharField()
    speaker_confidence = serializers.FloatField(allow_null=True)

    # Quality
    confidence = serializers.FloatField(allow_null=True)

    def get_speaker_anchor_id(self, obj):
        if obj.speaker_anchor:
            return str(obj.speaker_anchor.id)
        return None


class TranscriptionSerializer(serializers.Serializer):
    """
    Read serializer for Transcription.
    """
    id = serializers.UUIDField(read_only=True)
    recording_id = serializers.SerializerMethodField()
    version = serializers.IntegerField()

    # Content
    text = serializers.CharField()
    language = serializers.CharField()

    # Quality
    confidence_avg = serializers.FloatField(allow_null=True)

    # Model info
    whisper_model = serializers.CharField()

    # Processing
    processing_started_at = serializers.DateTimeField(allow_null=True)
    processing_completed_at = serializers.DateTimeField(allow_null=True)

    # Timestamps
    created_at = serializers.DateTimeField(read_only=True)

    # Nested segments (optional, for detail view)
    segments = TranscriptSegmentSerializer(many=True, read_only=True)

    def get_recording_id(self, obj):
        return str(obj.recording.id)


class TranscriptionListSerializer(serializers.Serializer):
    """
    Lightweight serializer for listing transcriptions.
    """
    id = serializers.UUIDField(read_only=True)
    recording_id = serializers.SerializerMethodField()
    version = serializers.IntegerField()
    language = serializers.CharField()
    whisper_model = serializers.CharField()
    confidence_avg = serializers.FloatField(allow_null=True)
    segment_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)

    def get_recording_id(self, obj):
        return str(obj.recording.id)

    def get_segment_count(self, obj):
        return obj.segments.count()


# ============================================================================
# Bulk Upload Serializers
# ============================================================================

class BulkUploadSerializer(serializers.Serializer):
    """
    Serializer for bulk session upload via zip file.

    Expected zip structure:
    session-folder-1/
    ├── part-01.mp3
    ├── part-02.mp3
    └── part-03.mp3
    session-folder-2/
    ├── recording-01.mkv  (will be converted to WAV)
    └── recording-02.mkv
    """
    file = serializers.FileField(
        help_text="Zip file containing folders of audio/video files"
    )
    auto_transcribe = serializers.BooleanField(
        default=True,
        help_text="Automatically queue transcription for all recordings"
    )
    whisper_model = serializers.ChoiceField(
        choices=['tiny', 'base', 'small', 'medium', 'large', 'large-v3'],
        default='base',
        help_text="Whisper model to use for transcription"
    )

    def validate_file(self, file):
        """Validate the uploaded file is a zip."""
        # Check content type
        if file.content_type not in ['application/zip', 'application/x-zip-compressed']:
            # Also check by extension as content_type can be unreliable
            if not file.name.lower().endswith('.zip'):
                raise serializers.ValidationError(
                    f"File must be a zip archive. Got: {file.content_type}"
                )

        # Check file size (max 2GB)
        max_size = 2 * 1024 * 1024 * 1024  # 2GB
        if file.size > max_size:
            raise serializers.ValidationError(
                f"Zip file too large. Maximum size is 2GB, got {file.size / (1024*1024*1024):.2f}GB"
            )

        return file


class BulkUploadResultSerializer(serializers.Serializer):
    """
    Serializer for bulk upload result.
    """
    status = serializers.CharField()
    batch_id = serializers.CharField()
    library_id = serializers.CharField(allow_null=True)
    sessions_created = serializers.IntegerField()
    recordings_created = serializers.IntegerField()
    transcription_tasks_queued = serializers.IntegerField()
    sessions = serializers.ListField(child=serializers.DictField())
    errors = serializers.ListField(child=serializers.CharField())
    warnings = serializers.ListField(child=serializers.CharField())


class MultiFileUploadSerializer(serializers.Serializer):
    """
    Serializer for multi-file upload with paths.

    Accepts multiple files with their relative paths for smart session grouping:
    - Single file → one Recording (no session)
    - Multiple files at root → one Session
    - Files in subdirectories → each subdirectory becomes a Session

    Frontend sends:
    - files: array of File objects
    - paths: JSON array of relative paths (from webkitRelativePath)
    """
    # Note: files are handled separately via request.FILES.getlist('files')
    paths = serializers.CharField(
        help_text="JSON array of relative paths corresponding to uploaded files"
    )
    auto_transcribe = serializers.BooleanField(
        default=True,
        help_text="Automatically queue transcription for all recordings"
    )
    whisper_model = serializers.ChoiceField(
        choices=['tiny', 'base', 'small', 'medium', 'large', 'large-v3'],
        default='base',
        help_text="Whisper model to use for transcription"
    )
    session_title = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional title for session (used when files create single session)"
    )

    def validate_paths(self, value):
        """Parse and validate paths JSON."""
        import json
        try:
            paths = json.loads(value)
            if not isinstance(paths, list):
                raise serializers.ValidationError("paths must be a JSON array")
            return paths
        except json.JSONDecodeError:
            raise serializers.ValidationError("Invalid JSON in paths field")
