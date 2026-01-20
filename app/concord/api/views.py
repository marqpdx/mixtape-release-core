# concord/api/views.py
# ============================================================================
# Concord API Views
#
# Models inherit from BaseContent, so use:
# - submitted_by (not created_by) for who uploaded
# - body (not description) for detailed notes
# - summary for short description
# ============================================================================

import hashlib
import uuid
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from concord.models import (
    Recording,
    RecordingStatus,
    RecordingSession,
    SessionStatus,
    SpeakerAnchor,
    Transcription,
    TranscriptSegment,
)
from .serializers import (
    RecordingSerializer,
    RecordingCreateSerializer,
    RecordingUpdateSerializer,
    RecordingUploadSerializer,
    RecordingListSerializer,
    RecordingSessionSerializer,
    RecordingSessionCreateSerializer,
    RecordingSessionUpdateSerializer,
    RecordingSessionListSerializer,
    SpeakerAnchorSerializer,
    SpeakerAnchorCreateSerializer,
    SpeakerAnchorUpdateSerializer,
    SpeakerAnchorListSerializer,
    TranscriptionSerializer,
    TranscriptionListSerializer,
    BulkUploadSerializer,
    MultiFileUploadSerializer,
)


# ============================================================================
# List & Create Recordings
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def recording_list_create(request):
    """
    GET: List recordings for a sponsor (group or user)
    POST: Create a new recording

    Query params for GET:
    - sponsor_type: 'group' or 'user' (required)
    - sponsor_id: UUID of sponsor (required)
    - status: filter by status (optional)
    """
    if request.method == 'GET':
        return list_recordings(request)
    else:
        return create_recording(request)


def list_recordings(request):
    """List recordings for a sponsor"""
    sponsor_type = request.query_params.get('sponsor_type')
    sponsor_id = request.query_params.get('sponsor_id')
    status_filter = request.query_params.get('status')

    if not sponsor_type or not sponsor_id:
        return Response(
            {'error': 'sponsor_type and sponsor_id are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get content type for sponsor
    try:
        if sponsor_type == 'group':
            from groups.models import Group
            content_type = ContentType.objects.get_for_model(Group)
        elif sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            content_type = ContentType.objects.get_for_model(User)
        else:
            return Response(
                {'error': f"Invalid sponsor_type: {sponsor_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Query recordings
    queryset = Recording.objects.filter(
        sponsor_content_type=content_type,
        sponsor_object_id=sponsor_id
    ).select_related('submitted_by', 'author')

    # Apply status filter
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # Order by most recent
    queryset = queryset.order_by('-created_at')

    # Serialize
    serializer = RecordingListSerializer(queryset, many=True)
    return Response({
        'recordings': serializer.data,
        'count': queryset.count()
    })


def create_recording(request):
    """Create a new recording"""
    serializer = RecordingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    sponsor_type = data['sponsor_type']
    sponsor_id = data['sponsor_id']

    # Get sponsor object and content type
    if sponsor_type == 'group':
        from groups.models import Group
        sponsor = Group.objects.get(id=sponsor_id)
        content_type = ContentType.objects.get_for_model(Group)
    else:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        sponsor = User.objects.get(id=sponsor_id)
        content_type = ContentType.objects.get_for_model(User)

    # Create recording (using BaseContent fields)
    recording = Recording.objects.create(
        sponsor_content_type=content_type,
        sponsor_object_id=sponsor_id,
        title=data.get('title', ''),
        summary=data.get('summary', ''),
        body=data.get('body', ''),
        recorded_at=data.get('recorded_at'),
        submitted_by=request.user,
        status=RecordingStatus.UPLOADED
    )

    # Handle file upload if provided
    if 'file' in data:
        upload_file_to_recording(recording, data['file'])

    # Return created recording
    response_serializer = RecordingSerializer(recording)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


# ============================================================================
# Recording Detail
# ============================================================================

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def recording_detail(request, recording_id):
    """
    GET: Get recording details
    PATCH: Update recording metadata
    DELETE: Archive recording
    """
    try:
        recording = Recording.objects.select_related(
            'submitted_by', 'author', 'source_file', 'asset'
        ).get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = RecordingSerializer(recording)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = RecordingUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Update fields (using BaseContent field names)
        data = serializer.validated_data
        if 'title' in data:
            recording.title = data['title']
        if 'summary' in data:
            recording.summary = data['summary']
        if 'body' in data:
            recording.body = data['body']
        if 'recorded_at' in data:
            recording.recorded_at = data['recorded_at']

        recording.save()

        response_serializer = RecordingSerializer(recording)
        return Response(response_serializer.data)

    elif request.method == 'DELETE':
        # Soft delete by archiving
        recording.status = RecordingStatus.ARCHIVED
        recording.status_changed_at = timezone.now()
        recording.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# File Upload
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recording_upload(request, recording_id):
    """
    Upload audio file to an existing recording.
    """
    try:
        recording = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate file
    serializer = RecordingUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    file = serializer.validated_data['file']

    # Upload file
    upload_file_to_recording(recording, file)

    # Return updated recording
    response_serializer = RecordingSerializer(recording)
    return Response(response_serializer.data)


def upload_file_to_recording(recording, file):
    """
    Upload file to storage and update recording.
    """
    # Generate storage path
    sponsor_type = recording.sponsor_content_type.model
    sponsor_id = str(recording.sponsor_object_id)
    recording_id = str(recording.id)
    filename = file.name

    storage_path = f"recordings/{sponsor_type}/{sponsor_id}/{recording_id}/{filename}"

    # Upload to storage
    saved_path = default_storage.save(storage_path, file)

    # Calculate hash
    file.seek(0)
    file_hash = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)

    # Update recording
    recording.audio_path = saved_path
    recording.audio_content_type = file.content_type
    recording.audio_size_bytes = file.size
    recording.save()

    return saved_path


# ============================================================================
# Status Transitions
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recording_transition(request, recording_id):
    """
    Transition recording to a new status.

    Body:
    - status: new status value
    """
    try:
        recording = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    new_status = request.data.get('status')
    if not new_status:
        return Response(
            {'error': 'status is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate status value
    valid_statuses = [choice[0] for choice in RecordingStatus.choices]
    if new_status not in valid_statuses:
        return Response(
            {'error': f"Invalid status: {new_status}. Valid values: {valid_statuses}"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        recording.transition_to(new_status)
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

    response_serializer = RecordingSerializer(recording)
    return Response(response_serializer.data)


# ============================================================================
# Group-specific endpoints (convenience)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_recordings(request, group_slug):
    """
    List recordings for a specific group by slug.
    Convenience endpoint for frontend.
    """
    from groups.models import Group

    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    content_type = ContentType.objects.get_for_model(Group)
    queryset = Recording.objects.filter(
        sponsor_content_type=content_type,
        sponsor_object_id=group.id
    ).select_related('submitted_by', 'author').order_by('-created_at')

    # Apply status filter
    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    serializer = RecordingListSerializer(queryset, many=True)
    return Response({
        'recordings': serializer.data,
        'count': queryset.count(),
        'group': {
            'id': str(group.id),
            'slug': group.slug,
            'title': group.title
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def group_recording_create(request, group_slug):
    """
    Create a recording for a specific group by slug.
    Convenience endpoint for frontend.
    """
    from groups.models import Group

    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Add sponsor info to request data
    data = request.data.copy()
    data['sponsor_type'] = 'group'
    data['sponsor_id'] = str(group.id)

    serializer = RecordingCreateSerializer(data=data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated_data = serializer.validated_data
    content_type = ContentType.objects.get_for_model(Group)

    # Create recording (using BaseContent fields)
    recording = Recording.objects.create(
        sponsor_content_type=content_type,
        sponsor_object_id=group.id,
        title=validated_data.get('title', ''),
        summary=validated_data.get('summary', ''),
        body=validated_data.get('body', ''),
        recorded_at=validated_data.get('recorded_at'),
        submitted_by=request.user,
        status=RecordingStatus.UPLOADED
    )

    # Handle file upload if provided
    if 'file' in validated_data:
        upload_file_to_recording(recording, validated_data['file'])

    response_serializer = RecordingSerializer(recording)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


# ============================================================================
# RecordingSession Endpoints
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def session_list_create(request):
    """
    GET: List recording sessions for a sponsor
    POST: Create a new recording session

    Query params for GET:
    - sponsor_type: 'group' or 'user' (required)
    - sponsor_id: UUID of sponsor (required)
    - status: filter by status (optional)
    """
    if request.method == 'GET':
        return list_sessions(request)
    else:
        return create_session(request)


def list_sessions(request):
    """List recording sessions for a sponsor"""
    sponsor_type = request.query_params.get('sponsor_type')
    sponsor_id = request.query_params.get('sponsor_id')
    status_filter = request.query_params.get('status')

    if not sponsor_type or not sponsor_id:
        return Response(
            {'error': 'sponsor_type and sponsor_id are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get content type for sponsor
    try:
        if sponsor_type == 'group':
            from groups.models import Group
            content_type = ContentType.objects.get_for_model(Group)
        elif sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            content_type = ContentType.objects.get_for_model(User)
        else:
            return Response(
                {'error': f"Invalid sponsor_type: {sponsor_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Query sessions
    queryset = RecordingSession.objects.filter(
        sponsor_content_type=content_type,
        sponsor_object_id=sponsor_id
    ).select_related('submitted_by').prefetch_related('segments')

    # Apply status filter
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # Order by most recent
    queryset = queryset.order_by('-created_at')

    serializer = RecordingSessionListSerializer(queryset, many=True)
    return Response({
        'sessions': serializer.data,
        'count': queryset.count()
    })


def create_session(request):
    """Create a new recording session"""
    serializer = RecordingSessionCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    sponsor_type = data['sponsor_type']
    sponsor_id = data['sponsor_id']

    # Get content type
    if sponsor_type == 'group':
        from groups.models import Group
        content_type = ContentType.objects.get_for_model(Group)
    else:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        content_type = ContentType.objects.get_for_model(User)

    # Create session
    session = RecordingSession.objects.create(
        sponsor_content_type=content_type,
        sponsor_object_id=sponsor_id,
        title=data.get('title', ''),
        summary=data.get('summary', ''),
        body=data.get('body', ''),
        external_call_id=data.get('external_call_id', ''),
        session_started_at=data.get('session_started_at'),
        segment_duration_seconds=data.get('segment_duration_seconds', 900),
        expected_participants=data.get('expected_participants', []),
        submitted_by=request.user,
        status=SessionStatus.RECORDING
    )

    response_serializer = RecordingSessionSerializer(session)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def session_detail(request, session_id):
    """
    GET: Get session details with segments
    PATCH: Update session metadata
    DELETE: Archive session
    """
    try:
        session = RecordingSession.objects.select_related(
            'submitted_by'
        ).prefetch_related('segments').get(id=session_id)
    except RecordingSession.DoesNotExist:
        return Response(
            {'error': 'Session not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = RecordingSessionSerializer(session)
        # Include segments in response
        segments = session.segments.order_by('segment_index', 'track_type')
        segments_serializer = RecordingListSerializer(segments, many=True)
        response_data = serializer.data
        response_data['segments'] = segments_serializer.data
        return Response(response_data)

    elif request.method == 'PATCH':
        serializer = RecordingSessionUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        for field in ['title', 'summary', 'body', 'external_call_id',
                      'session_started_at', 'session_ended_at',
                      'expected_participants', 'status']:
            if field in data:
                setattr(session, field, data[field])

        session.save()
        response_serializer = RecordingSessionSerializer(session)
        return Response(response_serializer.data)

    elif request.method == 'DELETE':
        session.status = SessionStatus.ARCHIVED
        session.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_sessions(request, group_slug):
    """
    List recording sessions for a specific group by slug.
    """
    from groups.models import Group

    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    content_type = ContentType.objects.get_for_model(Group)
    queryset = RecordingSession.objects.filter(
        sponsor_content_type=content_type,
        sponsor_object_id=group.id
    ).select_related('submitted_by').prefetch_related('segments').order_by('-created_at')

    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    serializer = RecordingSessionListSerializer(queryset, many=True)
    return Response({
        'sessions': serializer.data,
        'count': queryset.count(),
        'group': {
            'id': str(group.id),
            'slug': group.slug,
            'title': group.title
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def group_session_create(request, group_slug):
    """
    Create a recording session for a specific group by slug.
    """
    from groups.models import Group

    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    data = request.data.copy()
    data['sponsor_type'] = 'group'
    data['sponsor_id'] = str(group.id)

    serializer = RecordingSessionCreateSerializer(data=data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validated_data = serializer.validated_data
    content_type = ContentType.objects.get_for_model(Group)

    session = RecordingSession.objects.create(
        sponsor_content_type=content_type,
        sponsor_object_id=group.id,
        title=validated_data.get('title', ''),
        summary=validated_data.get('summary', ''),
        body=validated_data.get('body', ''),
        external_call_id=validated_data.get('external_call_id', ''),
        session_started_at=validated_data.get('session_started_at'),
        segment_duration_seconds=validated_data.get('segment_duration_seconds', 900),
        expected_participants=validated_data.get('expected_participants', []),
        submitted_by=request.user,
        status=SessionStatus.RECORDING
    )

    response_serializer = RecordingSessionSerializer(session)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


# ============================================================================
# SpeakerAnchor Endpoints
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def anchor_list_create(request):
    """
    GET: List speaker anchors for a session or group
    POST: Create a new speaker anchor

    Query params for GET:
    - session_id: UUID of session (optional)
    - group_id: UUID of group (optional)
    At least one must be provided.
    """
    if request.method == 'GET':
        return list_anchors(request)
    else:
        return create_anchor(request)


def list_anchors(request):
    """List speaker anchors"""
    session_id = request.query_params.get('session_id')
    group_id = request.query_params.get('group_id')

    if not session_id and not group_id:
        return Response(
            {'error': 'session_id or group_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    queryset = SpeakerAnchor.objects.select_related('user', 'session', 'group')

    if session_id:
        queryset = queryset.filter(session_id=session_id)
    if group_id:
        queryset = queryset.filter(group_id=group_id)

    # Only active by default
    include_inactive = request.query_params.get('include_inactive', 'false').lower() == 'true'
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    queryset = queryset.order_by('speaker_label')

    serializer = SpeakerAnchorListSerializer(queryset, many=True)
    return Response({
        'anchors': serializer.data,
        'count': queryset.count()
    })


def create_anchor(request):
    """Create a new speaker anchor"""
    serializer = SpeakerAnchorCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    # Get related objects
    session = None
    group = None
    user = None
    source_recording = None

    if data.get('session_id'):
        session = RecordingSession.objects.get(id=data['session_id'])
    if data.get('group_id'):
        from groups.models import Group
        group = Group.objects.get(id=data['group_id'])
    if data.get('user_id'):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(id=data['user_id'])
    if data.get('source_recording_id'):
        source_recording = Recording.objects.get(id=data['source_recording_id'])

    anchor = SpeakerAnchor.objects.create(
        session=session,
        group=group,
        speaker_label=data['speaker_label'],
        user=user,
        source_recording=source_recording,
        sample_start_ms=data.get('sample_start_ms'),
        sample_end_ms=data.get('sample_end_ms'),
    )

    response_serializer = SpeakerAnchorSerializer(anchor)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def anchor_detail(request, anchor_id):
    """
    GET: Get anchor details
    PATCH: Update anchor
    DELETE: Deactivate anchor (soft delete)
    """
    try:
        anchor = SpeakerAnchor.objects.select_related(
            'user', 'session', 'group', 'source_recording'
        ).get(id=anchor_id)
    except SpeakerAnchor.DoesNotExist:
        return Response(
            {'error': 'Speaker anchor not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = SpeakerAnchorSerializer(anchor)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = SpeakerAnchorUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        if 'speaker_label' in data:
            anchor.speaker_label = data['speaker_label']
        if 'is_active' in data:
            anchor.is_active = data['is_active']
        if 'confidence_score' in data:
            anchor.confidence_score = data['confidence_score']
        if 'user_id' in data:
            if data['user_id']:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                anchor.user = User.objects.get(id=data['user_id'])
            else:
                anchor.user = None

        anchor.save()
        response_serializer = SpeakerAnchorSerializer(anchor)
        return Response(response_serializer.data)

    elif request.method == 'DELETE':
        # Soft delete by deactivating
        anchor.is_active = False
        anchor.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_anchors(request, session_id):
    """
    List speaker anchors for a specific session.
    """
    try:
        session = RecordingSession.objects.get(id=session_id)
    except RecordingSession.DoesNotExist:
        return Response(
            {'error': 'Session not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    queryset = SpeakerAnchor.objects.filter(
        session=session
    ).select_related('user').order_by('speaker_label')

    include_inactive = request.query_params.get('include_inactive', 'false').lower() == 'true'
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    serializer = SpeakerAnchorListSerializer(queryset, many=True)
    return Response({
        'anchors': serializer.data,
        'count': queryset.count(),
        'session_id': str(session.id)
    })


# ============================================================================
# Transcription Endpoints (Read-Only)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transcription_list(request):
    """
    List transcriptions for a recording.

    Query params:
    - recording_id: UUID of recording (required)
    """
    recording_id = request.query_params.get('recording_id')

    if not recording_id:
        return Response(
            {'error': 'recording_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        recording = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    queryset = Transcription.objects.filter(
        recording=recording
    ).prefetch_related('segments').order_by('-version')

    serializer = TranscriptionListSerializer(queryset, many=True)
    return Response({
        'transcriptions': serializer.data,
        'count': queryset.count(),
        'recording_id': str(recording.id)
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transcription_detail(request, transcription_id):
    """
    Get transcription details with all segments.
    """
    try:
        transcription = Transcription.objects.prefetch_related(
            'segments', 'segments__speaker_anchor'
        ).get(id=transcription_id)
    except Transcription.DoesNotExist:
        return Response(
            {'error': 'Transcription not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = TranscriptionSerializer(transcription)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recording_transcriptions(request, recording_id):
    """
    List transcriptions for a specific recording.
    Convenience endpoint.
    """
    try:
        recording = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    queryset = Transcription.objects.filter(
        recording=recording
    ).prefetch_related('segments').order_by('-version')

    serializer = TranscriptionListSerializer(queryset, many=True)
    return Response({
        'transcriptions': serializer.data,
        'count': queryset.count(),
        'recording_id': str(recording.id)
    })


# ============================================================================
# Transcription Trigger Endpoint
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_transcription(request, recording_id):
    """
    Trigger transcription for a recording.

    This queues a Celery task to transcribe the recording using Whisper.

    Body (optional):
    - model: Whisper model size (tiny, base, small, medium, large, large-v3)
    - language: Language code (e.g., 'en'). Auto-detect if not provided.

    Returns:
    - task_id: Celery task ID for tracking
    - status: 'queued' or error message
    """
    try:
        recording = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return Response(
            {'error': 'Recording not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Check if recording has audio
    if not recording.audio_path and not recording.source_file and not recording.asset:
        return Response(
            {'error': 'Recording has no audio file'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if already transcribing
    if recording.status == RecordingStatus.TRANSCRIBING:
        return Response(
            {'error': 'Recording is already being transcribed'},
            status=status.HTTP_409_CONFLICT
        )

    # Check if already has transcription (allow re-transcription with force=true)
    force = request.data.get('force', False)
    if recording.transcriptions.exists() and not force:
        return Response(
            {
                'error': 'Recording already has transcription. Use force=true to re-transcribe.',
                'transcription_count': recording.transcriptions.count()
            },
            status=status.HTTP_409_CONFLICT
        )

    # Get options
    model_name = request.data.get('model', 'base')
    language = request.data.get('language', None)

    # Validate model name
    valid_models = ['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']
    if model_name not in valid_models:
        return Response(
            {'error': f"Invalid model: {model_name}. Valid models: {valid_models}"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Queue transcription task
    from concord.tasks.transcription import transcribe_recording_task

    task = transcribe_recording_task.delay(
        recording_id=str(recording.id),
        model_name=model_name,
        language=language,
        force=force,
    )

    return Response({
        'status': 'queued',
        'task_id': str(task.id),
        'recording_id': str(recording.id),
        'model': model_name,
        'language': language,
    }, status=status.HTTP_202_ACCEPTED)


# ============================================================================
# Bulk Session Upload
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def group_sessions_bulk_upload(request, group_slug):
    """
    Bulk upload sessions from a zip file.

    POST /api/concord/groups/{slug}/sessions/bulk-upload/
    Content-Type: multipart/form-data

    Parameters:
    - file: Zip file containing folders of audio/video files
    - auto_transcribe: bool (default: true) - Queue transcription tasks
    - whisper_model: str (default: 'base') - Whisper model size

    Expected zip structure:
    lecture-22Jan2026/
    ├── part-01.mp3
    ├── part-02.mp3
    └── part-03.mp3
    meeting-notes/
    ├── recording-01.mkv  (auto-converted to WAV)
    └── recording-02.mkv

    Each folder becomes a RecordingSession.
    Each audio/video file becomes a Recording.
    MKV and video files are auto-converted to WAV for Whisper.
    A Library is auto-created for the batch.

    Returns:
    - status: 'success' or 'error'
    - batch_id: UUID for this import batch
    - library_id: UUID of created Library
    - sessions_created: count
    - recordings_created: count
    - transcription_tasks_queued: count
    - sessions: list of created sessions
    - errors: list of error messages
    - warnings: list of warning messages
    """
    from groups.models import Group
    from concord.services.bulk_import import BulkImportService

    # Get group
    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate request
    serializer = BulkUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    zip_file = data['file']

    # Create service and run import
    service = BulkImportService(
        group=group,
        user=request.user,
        auto_transcribe=data.get('auto_transcribe', True),
        whisper_model=data.get('whisper_model', 'base'),
    )

    result = service.import_zip(zip_file, zip_filename=zip_file.name)

    # Build response
    response_data = {
        'status': 'success' if result.success else 'error',
        'batch_id': result.batch_id,
        'library_id': result.library_id,
        'sessions_created': result.sessions_created,
        'recordings_created': result.recordings_created,
        'transcription_tasks_queued': result.transcription_tasks_queued,
        'sessions': result.sessions,
        'errors': result.errors,
        'warnings': result.warnings,
    }

    if result.success:
        return Response(response_data, status=status.HTTP_201_CREATED)
    else:
        return Response(response_data, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def group_upload(request, group_slug):
    """
    Unified upload endpoint for audio/video files.

    POST /api/concord/groups/{slug}/upload/
    Content-Type: multipart/form-data

    Handles multiple upload scenarios:
    1. Single file → standalone Recording (no Session)
    2. Multiple files at root → one Session with multiple Recordings
    3. Directory upload → files grouped by subdirectory, each = Session
    4. Zip file → extracted, folders = Sessions

    Parameters:
    - files: One or more audio/video files (or single zip)
    - paths: JSON array of relative paths (from webkitRelativePath)
    - auto_transcribe: bool (default: true)
    - whisper_model: str (default: 'base')
    - session_title: str (optional) - title for single-session uploads

    Path examples:
    - ["file1.mp3"] → 1 standalone Recording
    - ["file1.mp3", "file2.mp3"] → 1 Session with 2 Recordings
    - ["lectures/part1.mp3", "lectures/part2.mp3"] → 1 Session "lectures"
    - ["lec1/a.mp3", "lec2/b.mp3"] → 2 Sessions

    Returns same format as bulk-upload endpoint.
    """
    from groups.models import Group
    from concord.services.bulk_import import BulkImportService

    # Get group
    try:
        group = Group.objects.get(slug=group_slug)
    except Group.DoesNotExist:
        return Response(
            {'error': f"Group '{group_slug}' not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get files from request
    files = request.FILES.getlist('files')

    if not files:
        return Response(
            {'error': 'No files provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if single zip file
    if len(files) == 1 and files[0].name.lower().endswith('.zip'):
        # Use zip import path
        serializer = BulkUploadSerializer(data={
            'file': files[0],
            'auto_transcribe': request.data.get('auto_transcribe', True),
            'whisper_model': request.data.get('whisper_model', 'base'),
        })
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        service = BulkImportService(
            group=group,
            user=request.user,
            auto_transcribe=data.get('auto_transcribe', True),
            whisper_model=data.get('whisper_model', 'base'),
        )
        result = service.import_zip(data['file'], zip_filename=data['file'].name)

    else:
        # Multi-file upload path
        serializer = MultiFileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        paths = data['paths']

        # If paths not provided or empty, use filenames as paths
        if not paths:
            paths = [f.name for f in files]

        service = BulkImportService(
            group=group,
            user=request.user,
            auto_transcribe=data.get('auto_transcribe', True),
            whisper_model=data.get('whisper_model', 'base'),
        )

        result = service.import_files(
            files=files,
            paths=paths,
            session_title=data.get('session_title', ''),
        )

    # Build response
    response_data = {
        'status': 'success' if result.success else 'error',
        'batch_id': result.batch_id,
        'library_id': result.library_id,
        'sessions_created': result.sessions_created,
        'recordings_created': result.recordings_created,
        'transcription_tasks_queued': result.transcription_tasks_queued,
        'sessions': result.sessions,
        'errors': result.errors,
        'warnings': result.warnings,
    }

    if result.success:
        return Response(response_data, status=status.HTTP_201_CREATED)
    else:
        return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
