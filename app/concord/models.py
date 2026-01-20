# concord/models.py
# ============================================================================
# Audio Transcription & Interpretation Layer
#
# This module implements the Concord architecture for audio capture, including:
# - RecordingSession: Groups segmented recordings from a single call/meeting
# - Recording: Individual audio segment (inherits BaseContent)
# - SpeakerAnchor: Voice print for contextual speaker identification
# - Transcription: Whisper ASR output
# - TranscriptSegment: Speaker turns within a transcription
#
# See: docs/planning/audio/architecture.md
# See: docs/planning/audio/surfaces.md
# ============================================================================

import uuid
from django.conf import settings
from django.db import models

from fundamentals.models import BaseContent
from fundamentals.bases import BaseModel


# ============================================================================
# Enumerations
# ============================================================================

class SessionStatus(models.TextChoices):
    """Recording session lifecycle states."""
    RECORDING = 'recording', 'Recording'
    COMPLETED = 'completed', 'Completed'
    PROCESSING = 'processing', 'Processing'
    READY = 'ready', 'Ready'
    ARCHIVED = 'archived', 'Archived'


class RecordingStatus(models.TextChoices):
    """
    Recording processing state machine.

    Transitions:
    - uploaded → transcribing (Whisper job starts)
    - transcribing → interpreting (Whisper complete, Concord starts)
    - interpreting → ready (Concord complete, awaiting EchoLine review)
    - ready → accepted (Human accepts in EchoLine)
    - accepted → promoted (MillDraft created)
    - any → archived (User archives recording)
    - any → failed (Processing error)
    """
    UPLOADED = 'uploaded', 'Uploaded'
    TRANSCRIBING = 'transcribing', 'Transcribing'
    INTERPRETING = 'interpreting', 'Interpreting'
    READY = 'ready', 'Ready for Review'
    ACCEPTED = 'accepted', 'Accepted'
    PROMOTED = 'promoted', 'Promoted'
    ARCHIVED = 'archived', 'Archived'
    FAILED = 'failed', 'Failed'


class TrackType(models.TextChoices):
    """Audio track types for multi-track capture."""
    MIXED = 'mixed', 'Mixed Audio'
    MICROPHONE = 'microphone', 'Microphone Only'
    SYSTEM = 'system', 'System Audio Only'
    SPEAKER_SAMPLE = 'speaker_sample', 'Speaker Voice Sample'


# ============================================================================
# RecordingSession Model
# ============================================================================

class RecordingSession(BaseContent):
    """
    A capture session grouping multiple Recording segments from a single call/meeting.

    Per surfaces.md:
    - Recordings should be segmented at capture time (10-15 min segments)
    - Each segment becomes one Recording
    - Session tracks overall call metadata and participant info

    Inherits from BaseContent for:
    - sponsor (Group/User)
    - title, slug, summary, body
    - timestamps, authorship
    """

    # ---- Session Identification ----
    external_call_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="External identifier (e.g., Zoom meeting ID)"
    )

    # ---- Timing ----
    session_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the session/call actually started"
    )
    session_ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the session/call ended"
    )

    # ---- Segment Configuration ----
    segment_duration_seconds = models.PositiveIntegerField(
        default=900,  # 15 minutes
        help_text="Target segment duration in seconds"
    )

    # ---- Participant Tracking ----
    expected_participants = models.JSONField(
        default=list,
        blank=True,
        help_text="List of expected participant names/identifiers"
    )

    # ---- Status ----
    status = models.CharField(
        max_length=20,
        choices=SessionStatus.choices,
        default=SessionStatus.RECORDING,
        db_index=True
    )

    class Meta(BaseContent.Meta):
        ordering = ['-created_at']
        verbose_name = "Recording Session"
        verbose_name_plural = "Recording Sessions"

    def __str__(self):
        title = self.title or f"Session {str(self.id)[:8]}"
        return f"{title} ({self.status})"

    @property
    def segment_count(self):
        """Number of recording segments in this session."""
        return self.segments.count()

    @property
    def total_duration_ms(self):
        """Total duration across all segments."""
        return self.segments.aggregate(
            total=models.Sum('duration_ms')
        )['total'] or 0


# ============================================================================
# Recording Model
# ============================================================================

class Recording(BaseContent):
    """
    An individual audio segment within a recording session.

    Per surfaces.md:
    - Segment at capture time (10-15 minutes recommended)
    - Each segment becomes one SourceFile → Artifacts → Shards → Chunks
    - Deterministic filenames: call-2026-01-16T10-00_part-01.wav

    Inherits from BaseContent which provides:
    - id (UUID primary key)
    - title, slug, summary, body (content fields)
    - sponsor (polymorphic GenericFK to Group/User)
    - author, author_name, submitted_by (authorship)
    - tags, categories (GenericRelations for classification)
    - published_at, created_at, updated_at (timestamps)

    Can be standalone (simple upload) or part of a RecordingSession (segmented capture).
    """

    # ---- Session Link (for segmented recordings) ----
    session = models.ForeignKey(
        'RecordingSession',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='segments',
        help_text="Parent session for segmented recordings"
    )
    segment_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="0-based index within session (part-01 = 0)"
    )

    # ---- Track Type (for multi-track capture) ----
    track_type = models.CharField(
        max_length=20,
        choices=TrackType.choices,
        default=TrackType.MIXED,
        help_text="Type of audio track"
    )

    # ---- Voice Sample Flag ----
    is_voice_sample = models.BooleanField(
        default=False,
        help_text="True if this is a speaker identification sample"
    )

    # ---- Audio Metadata ----
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration in milliseconds"
    )
    recorded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the audio was originally recorded (if known)"
    )

    # ---- Processing State ----
    status = models.CharField(
        max_length=20,
        choices=RecordingStatus.choices,
        default=RecordingStatus.UPLOADED,
        db_index=True
    )
    status_changed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Last time status changed"
    )

    # ---- Storage Reference ----
    source_file = models.ForeignKey(
        'stackroom.SourceFile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recordings',
        help_text="Reference to the audio file in Stackroom"
    )
    asset = models.ForeignKey(
        'assets.Asset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recordings',
        help_text="Reference to the audio file as an Asset"
    )
    audio_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Direct S3 key for the audio file"
    )
    audio_content_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="MIME type of the audio file (e.g., audio/mpeg)"
    )
    audio_size_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes"
    )

    # ---- Processing Metadata ----
    processing_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When transcription processing began"
    )
    processing_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When processing completed (success or failure)"
    )
    processing_error = models.TextField(
        blank=True,
        default="",
        help_text="Error message if processing failed"
    )

    # ---- Promotion Link ----
    mill_draft = models.ForeignKey(
        'fundamentals.MillDraft',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_recordings',
        help_text="MillDraft created from this recording"
    )

    class Meta(BaseContent.Meta):
        ordering = ['-created_at']
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['session', 'segment_index']),
        ]

    def __str__(self):
        title = self.title or f"Recording {str(self.id)[:8]}"
        if self.session and self.segment_index is not None:
            return f"{title} (part {self.segment_index + 1})"
        return f"{title} ({self.status})"

    # ---- Properties ----

    @property
    def duration_seconds(self):
        """Return duration in seconds (convenience property)"""
        if self.duration_ms:
            return self.duration_ms / 1000
        return None

    @property
    def duration_formatted(self):
        """Return human-readable duration (e.g., '2:34')"""
        if not self.duration_ms:
            return None
        total_seconds = self.duration_ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"

    @property
    def audio_url(self):
        """Generate presigned URL for audio playback."""
        if self.source_file:
            from django.core.files.storage import default_storage
            return default_storage.url(self.source_file.path)
        elif self.asset:
            from django.core.files.storage import default_storage
            return default_storage.url(self.asset.file_path)
        elif self.audio_path:
            from django.core.files.storage import default_storage
            return default_storage.url(self.audio_path)
        return None

    # ---- Methods ----

    def transition_to(self, new_status):
        """
        Transition to a new status with timestamp update.
        Raises ValueError if transition is invalid.
        """
        from django.utils import timezone

        valid_transitions = {
            RecordingStatus.UPLOADED: [RecordingStatus.TRANSCRIBING, RecordingStatus.FAILED, RecordingStatus.ARCHIVED],
            RecordingStatus.TRANSCRIBING: [RecordingStatus.INTERPRETING, RecordingStatus.FAILED, RecordingStatus.ARCHIVED],
            RecordingStatus.INTERPRETING: [RecordingStatus.READY, RecordingStatus.FAILED, RecordingStatus.ARCHIVED],
            RecordingStatus.READY: [RecordingStatus.ACCEPTED, RecordingStatus.ARCHIVED],
            RecordingStatus.ACCEPTED: [RecordingStatus.PROMOTED, RecordingStatus.ARCHIVED],
            RecordingStatus.PROMOTED: [RecordingStatus.ARCHIVED],
            RecordingStatus.ARCHIVED: [],
            RecordingStatus.FAILED: [RecordingStatus.UPLOADED, RecordingStatus.ARCHIVED],
        }

        current = self.status
        if new_status not in valid_transitions.get(current, []):
            raise ValueError(
                f"Invalid transition from '{current}' to '{new_status}'. "
                f"Valid transitions: {valid_transitions.get(current, [])}"
            )

        self.status = new_status
        self.status_changed_at = timezone.now()

        if new_status == RecordingStatus.TRANSCRIBING:
            self.processing_started_at = timezone.now()
        elif new_status in [RecordingStatus.READY, RecordingStatus.FAILED]:
            self.processing_completed_at = timezone.now()

        self.save(update_fields=['status', 'status_changed_at', 'processing_started_at', 'processing_completed_at'])


# ============================================================================
# SpeakerAnchor Model (Voice Print)
# ============================================================================

class SpeakerAnchor(BaseModel):
    """
    A voice reference sample for speaker identification within a session/group.

    Per surfaces.md:
    - This is contextual speaker anchoring, NOT biometric authentication
    - NOT global voice identity
    - At call start, each participant says "This is Mark speaking"
    - 10-15 seconds of clean audio, no crosstalk

    What is stored:
    - A short reference embedding
    - A self-asserted speaker label
    - A session or group scope
    - A confidence score

    What is explicitly NOT claimed:
    - Identity verification
    - Cross-tenant recognition
    - Permanent biometric identity
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Scope: session-level or group-level ----
    session = models.ForeignKey(
        'RecordingSession',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='speaker_anchors',
        help_text="Session this anchor is scoped to (if session-specific)"
    )
    group = models.ForeignKey(
        'groups.Group',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='speaker_anchors',
        help_text="Group this anchor is scoped to (for cross-session use)"
    )

    # ---- Self-Asserted Identity ----
    speaker_label = models.CharField(
        max_length=100,
        help_text="Self-asserted name: 'This is Mark speaking'"
    )

    # ---- Optional Link to Mixtape User ----
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='speaker_anchors',
        help_text="Mixtape user if speaker is a known member"
    )

    # ---- Voice Sample Source ----
    source_recording = models.ForeignKey(
        'Recording',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voice_anchors',
        help_text="Recording containing the voice sample"
    )
    sample_start_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Start position of voice sample in source recording"
    )
    sample_end_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="End position of voice sample in source recording"
    )

    # ---- Embedding (the actual voice print) ----
    embedding = models.BinaryField(
        null=True,
        blank=True,
        help_text="Voice embedding vector (format TBD by model)"
    )
    embedding_model = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Model used to generate embedding"
    )

    # ---- Confidence ----
    confidence_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence in this anchor (0.0-1.0)"
    )

    # ---- Status ----
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this anchor should be used for matching"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'speaker_label']),
            models.Index(fields=['group', 'speaker_label']),
            models.Index(fields=['user']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(session__isnull=False) | models.Q(group__isnull=False),
                name='speaker_anchor_must_have_scope'
            )
        ]

    def __str__(self):
        scope = self.session or self.group
        return f"{self.speaker_label} ({scope})"


# ============================================================================
# Transcription Model
# ============================================================================

class Transcription(BaseModel):
    """
    Whisper ASR output for a Recording.

    Stores the raw transcription text, metadata about the transcription process,
    and links to TranscriptSegments for speaker turns.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Source ----
    recording = models.ForeignKey(
        'Recording',
        on_delete=models.CASCADE,
        related_name='transcriptions',
        help_text="Recording this transcription is derived from"
    )

    # ---- Version (allows re-transcription) ----
    version = models.PositiveIntegerField(
        default=1,
        help_text="Transcription version (for re-processing)"
    )

    # ---- Full Text ----
    text = models.TextField(
        blank=True,
        default="",
        help_text="Full transcription text"
    )

    # ---- Language ----
    language = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Detected or specified language code (e.g., 'en')"
    )

    # ---- Quality Indicators ----
    confidence_avg = models.FloatField(
        null=True,
        blank=True,
        help_text="Average confidence score across segments"
    )

    # ---- Model Info ----
    whisper_model = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Whisper model used (e.g., 'large-v3')"
    )

    # ---- Processing Timestamps ----
    processing_started_at = models.DateTimeField(
        null=True,
        blank=True
    )
    processing_completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [['recording', 'version']]
        indexes = [
            models.Index(fields=['recording', 'version']),
        ]

    def __str__(self):
        return f"Transcription v{self.version} for {self.recording}"


# ============================================================================
# TranscriptSegment Model
# ============================================================================

class TranscriptSegment(BaseModel):
    """
    A segment/turn within a transcription with speaker attribution.

    Per surfaces.md:
    - Whisper provides transcript + rough turns
    - Concord aligns turns against reference anchors (SpeakerAnchor)
    - Confidence improves over time within the same group
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Parent Transcription ----
    transcription = models.ForeignKey(
        'Transcription',
        on_delete=models.CASCADE,
        related_name='segments',
        help_text="Parent transcription"
    )

    # ---- Ordering ----
    segment_index = models.PositiveIntegerField(
        help_text="0-based index within transcription"
    )

    # ---- Timing ----
    start_ms = models.PositiveIntegerField(
        help_text="Start time in milliseconds"
    )
    end_ms = models.PositiveIntegerField(
        help_text="End time in milliseconds"
    )

    # ---- Content ----
    text = models.TextField(
        help_text="Segment text content"
    )

    # ---- Speaker Attribution ----
    speaker_anchor = models.ForeignKey(
        'SpeakerAnchor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transcript_segments',
        help_text="Matched speaker anchor (if identified)"
    )
    speaker_label = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Speaker label (from anchor or fallback 'Speaker A')"
    )
    speaker_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence in speaker attribution (0.0-1.0)"
    )

    # ---- Quality ----
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Transcription confidence for this segment"
    )

    class Meta:
        ordering = ['transcription', 'segment_index']
        indexes = [
            models.Index(fields=['transcription', 'segment_index']),
            models.Index(fields=['speaker_anchor']),
        ]

    def __str__(self):
        speaker = self.speaker_label or "Unknown"
        return f"[{self.start_ms}-{self.end_ms}] {speaker}: {self.text[:50]}..."

    @property
    def duration_ms(self):
        return self.end_ms - self.start_ms
