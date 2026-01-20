# Concord API Test Plan

**Module**: `concord` (Audio Transcription & Interpretation)
**Phase**: 1 & 2 - Recording, Sessions, Voice Prints & Transcription
**Date**: January 2025 (Updated)
**Author**: Claude (for Mark)
**Assignee**: Nick (Lead Test Engineer)

---

## Overview

The `concord` app provides audio recording management for groups and users. It supports:
- Segmented capture sessions (per `surfaces.md` recommendations)
- Voice prints for contextual speaker identification
- Whisper-based transcription with speaker attribution

Recordings inherit from `BaseContent`, enabling them to be added to Collections and integrated with the broader content system.

### Key Components
- **RecordingSession**: Groups segmented recordings from a single call/meeting
- **Recording**: Individual audio segment (inherits `BaseContent`)
- **SpeakerAnchor**: Voice print for contextual speaker identification (NOT biometric)
- **Transcription**: Whisper ASR output for a Recording
- **TranscriptSegment**: Speaker turns within a transcription
- **Status Machine**: uploaded → transcribing → interpreting → ready → accepted → promoted → archived
- **Storage**: Direct S3 path, Stackroom SourceFile, or Asset references
- **Sponsor Pattern**: Polymorphic FK to Group or User

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/concord/recordings/` | List recordings (requires `sponsor_type` & `sponsor_id`) |
| POST | `/api/concord/recordings/` | Create recording with explicit sponsor |
| GET | `/api/concord/recordings/{id}/` | Get recording detail |
| PATCH | `/api/concord/recordings/{id}/` | Update recording metadata |
| DELETE | `/api/concord/recordings/{id}/` | Archive recording (soft delete) |
| POST | `/api/concord/recordings/{id}/upload/` | Upload audio file to recording |
| POST | `/api/concord/recordings/{id}/transition/` | Transition recording status |
| GET | `/api/concord/groups/{slug}/recordings/` | List recordings for group (convenience) |
| POST | `/api/concord/groups/{slug}/recordings/create/` | Create recording for group (convenience) |

---

## Test Categories

### 1. Authentication & Authorization

#### 1.1 Authentication Required
```
TEST: All endpoints require authentication
- GET /api/concord/recordings/ without auth → 401
- POST /api/concord/recordings/ without auth → 401
- GET /api/concord/recordings/{id}/ without auth → 401
- All other endpoints without auth → 401
```

#### 1.2 Group Membership (Future)
```
TEST: User must be member of group to access group recordings
- Note: Currently no permission check beyond authentication
- TODO: Add group membership validation
```

---

### 2. Recording CRUD Operations

#### 2.1 List Recordings

```
TEST: List recordings requires sponsor_type and sponsor_id
- GET /api/concord/recordings/ → 400 (missing params)
- GET /api/concord/recordings/?sponsor_type=group → 400 (missing sponsor_id)
- GET /api/concord/recordings/?sponsor_id=xxx → 400 (missing sponsor_type)

TEST: List recordings with valid params
- GET /api/concord/recordings/?sponsor_type=group&sponsor_id={group_id} → 200
- Response contains: { recordings: [...], count: N }

TEST: List recordings filters by status
- GET /api/concord/recordings/?sponsor_type=group&sponsor_id={id}&status=uploaded → 200
- Only returns recordings with status='uploaded'

TEST: List recordings returns empty for new group
- Create new group, list recordings → { recordings: [], count: 0 }

TEST: Invalid sponsor_type returns 400
- GET /api/concord/recordings/?sponsor_type=invalid&sponsor_id={id} → 400
```

#### 2.2 Create Recording

```
TEST: Create recording with minimal data
- POST /api/concord/recordings/
  Body: { sponsor_type: "group", sponsor_id: "{uuid}" }
- Response: 201 with recording object
- Recording has status='uploaded', empty title/summary/body

TEST: Create recording with full metadata
- POST /api/concord/recordings/
  Body: {
    sponsor_type: "group",
    sponsor_id: "{uuid}",
    title: "Test Recording",
    summary: "Short description",
    body: "Detailed notes",
    recorded_at: "2025-01-15T10:00:00Z"
  }
- Response: 201
- All fields populated correctly
- slug auto-generated from title

TEST: Create recording with file upload
- POST /api/concord/recordings/ (multipart/form-data)
  Body: { sponsor_type, sponsor_id, title, file: audio.mp3 }
- Response: 201
- audio_path, audio_content_type, audio_size_bytes populated

TEST: Create recording with invalid sponsor
- POST /api/concord/recordings/
  Body: { sponsor_type: "group", sponsor_id: "nonexistent-uuid" }
- Response: 400 with validation error

TEST: Create recording sets submitted_by to current user
- Create recording → submitted_by matches authenticated user
```

#### 2.3 Get Recording Detail

```
TEST: Get existing recording
- GET /api/concord/recordings/{id}/ → 200
- Response contains all Recording fields

TEST: Get non-existent recording
- GET /api/concord/recordings/{fake-uuid}/ → 404

TEST: Response includes BaseContent fields
- slug, summary, body, author_name, published_at present in response
```

#### 2.4 Update Recording

```
TEST: Update title
- PATCH /api/concord/recordings/{id}/
  Body: { title: "New Title" }
- Response: 200, title updated

TEST: Update multiple fields
- PATCH /api/concord/recordings/{id}/
  Body: { title: "New", summary: "Updated summary", body: "New notes" }
- All fields updated

TEST: Update with empty body clears field
- PATCH /api/concord/recordings/{id}/
  Body: { body: "" }
- body field is empty string

TEST: Update non-existent recording
- PATCH /api/concord/recordings/{fake-uuid}/ → 404
```

#### 2.5 Delete (Archive) Recording

```
TEST: Delete archives recording
- DELETE /api/concord/recordings/{id}/ → 204
- GET /api/concord/recordings/{id}/ → status='archived'

TEST: Delete non-existent recording
- DELETE /api/concord/recordings/{fake-uuid}/ → 404

TEST: Archived recording excluded from default list (future)
- Note: Currently returns all statuses
- TODO: Consider filtering archived by default
```

---

### 3. File Upload

#### 3.1 Upload to Existing Recording

```
TEST: Upload valid audio file
- POST /api/concord/recordings/{id}/upload/ (multipart/form-data)
  Body: { file: test.mp3 }
- Response: 200
- audio_path contains storage path
- audio_content_type = 'audio/mpeg'
- audio_size_bytes matches file size

TEST: Upload updates existing audio (replaces)
- Upload file A, then upload file B
- audio_path points to file B
```

#### 3.2 File Validation

```
TEST: Reject non-audio file
- Upload .txt file → 400 "Unsupported audio format"
- Upload .jpg file → 400 "Unsupported audio format"

TEST: Accept various audio formats
- .mp3 (audio/mpeg) → 200
- .wav (audio/wav, audio/x-wav) → 200
- .m4a (audio/m4a, audio/mp4, audio/x-m4a) → 200
- .aac (audio/aac) → 200
- .ogg (audio/ogg) → 200
- .webm (audio/webm) → 200

TEST: Reject file exceeding 500MB
- Upload 501MB file → 400 "File too large"

TEST: Accept file at 500MB limit
- Upload exactly 500MB file → 200
```

#### 3.3 Storage Path

```
TEST: Storage path follows convention
- Upload file for group recording
- audio_path = "recordings/group/{group_id}/{recording_id}/{filename}"

TEST: Storage path for user-sponsored recording
- audio_path = "recordings/user/{user_id}/{recording_id}/{filename}"
```

---

### 4. Status Transitions

#### 4.1 Valid Transitions

```
TEST: uploaded → transcribing
- POST /api/concord/recordings/{id}/transition/
  Body: { status: "transcribing" }
- Response: 200, status='transcribing'
- processing_started_at is set

TEST: transcribing → interpreting
- Transition → 200, status='interpreting'

TEST: interpreting → ready
- Transition → 200, status='ready'
- processing_completed_at is set

TEST: ready → accepted
- Transition → 200, status='accepted'

TEST: accepted → promoted
- Transition → 200, status='promoted'

TEST: Any state → archived
- From uploaded → archived: 200
- From transcribing → archived: 200
- From ready → archived: 200

TEST: failed → uploaded (retry)
- Set status to failed, then transition to uploaded → 200
```

#### 4.2 Invalid Transitions

```
TEST: Cannot skip states
- uploaded → ready → 400 "Invalid transition"
- uploaded → accepted → 400

TEST: Cannot go backwards (except retry)
- ready → transcribing → 400
- accepted → ready → 400

TEST: archived is terminal
- archived → uploaded → 400
- archived → ready → 400

TEST: Invalid status value
- Body: { status: "invalid" } → 400 "Invalid status"
```

#### 4.3 Timestamp Tracking

```
TEST: status_changed_at updates on every transition
- Note initial status_changed_at
- Transition status
- status_changed_at is newer

TEST: processing_started_at set when entering transcribing
- Transition to transcribing
- processing_started_at is set, processing_completed_at is null

TEST: processing_completed_at set when entering ready or failed
- Transition to ready → processing_completed_at is set
- Transition to failed → processing_completed_at is set
```

---

### 5. Group Convenience Endpoints

#### 5.1 List Group Recordings

```
TEST: List by group slug
- GET /api/concord/groups/{slug}/recordings/ → 200
- Response includes group info: { id, slug, title }

TEST: Non-existent group
- GET /api/concord/groups/fake-slug/recordings/ → 404

TEST: Filter by status
- GET /api/concord/groups/{slug}/recordings/?status=uploaded → 200
- Only returns matching recordings
```

#### 5.2 Create Group Recording

```
TEST: Create via group slug
- POST /api/concord/groups/{slug}/recordings/create/
  Body: { title: "Test" }
- Response: 201
- sponsor_type='group', sponsor_id matches group

TEST: Create with file
- POST (multipart) with file → 201
- Audio file stored correctly

TEST: Non-existent group
- POST /api/concord/groups/fake-slug/recordings/create/ → 404
```

---

### 6. BaseContent Integration

#### 6.1 Slug Generation

```
TEST: Slug auto-generated from title
- Create with title "My Recording" → slug contains "my-recording"

TEST: Slug uniqueness
- Create two recordings with same title
- Slugs should be unique (e.g., "my-recording", "my-recording-1")

TEST: Empty title generates UUID-based slug
- Create with empty title → slug is generated (not empty)
```

#### 6.2 Sponsor Pattern

```
TEST: sponsor_type and sponsor_id in response
- GET recording → sponsor_type='group', sponsor_id='{uuid}'

TEST: sponsor object accessible (if needed)
- Internal: recording.sponsor returns Group/User object
```

#### 6.3 Authorship Fields

```
TEST: submitted_by set on create
- Create recording → submitted_by_id matches current user
- submitted_by_name contains user's display name

TEST: author fields (optional)
- author, author_name can be null initially
```

---

### 7. Edge Cases & Error Handling

```
TEST: Malformed UUID in path
- GET /api/concord/recordings/not-a-uuid/ → 404 or 400

TEST: Empty request body on create
- POST /api/concord/recordings/ with {} → 400 (missing required fields)

TEST: SQL injection in query params
- sponsor_id with SQL injection → 400 (invalid UUID format)

TEST: Very long title (over 100 chars)
- Create with 101+ char title → 400 or truncated

TEST: Unicode in title/body
- Create with emoji, non-Latin chars → 200, stored correctly

TEST: Concurrent uploads to same recording
- Two simultaneous uploads → last one wins, no corruption
```

---

### 8. Performance Considerations

```
TEST: List performance with many recordings
- Create 100+ recordings for a group
- List endpoint responds in < 500ms

TEST: Large file upload
- Upload 100MB file → completes without timeout
- Consider: chunked upload support (future)
```

---

## Phase 2: New Models

The following tests cover models added per `surfaces.md` requirements.

---

### 9. RecordingSession Model

#### 9.1 Session CRUD (Model Layer)

```
TEST: Create session with minimal data
- RecordingSession.objects.create(
    sponsor_content_type=..., sponsor_object_id=...,
    title="Team Standup"
  )
- status defaults to 'recording'
- segment_duration_seconds defaults to 900 (15 min)
- expected_participants defaults to empty list

TEST: Create session with full metadata
- external_call_id="zoom-12345"
- session_started_at=datetime.now()
- expected_participants=["Mark", "Nick", "Sarah"]
- All fields stored correctly

TEST: Session inherits BaseContent fields
- session.sponsor → Group or User object
- session.slug auto-generated from title
- session.submitted_by set correctly

TEST: Session timing validation
- session_started_at < session_ended_at (application logic)
- Both can be null initially
```

#### 9.2 Session Status Transitions

```
TEST: Session status states
- Valid statuses: recording, completed, processing, ready, archived
- Default is 'recording'

TEST: Session status can be updated
- session.status = SessionStatus.COMPLETED
- session.save() → status updated

TEST: Session archival
- Set status='archived' → session still accessible but marked archived
```

#### 9.3 Session-Recording Relationship

```
TEST: Add recordings to session
- Create session
- Create recording with session=session, segment_index=0
- Create recording with session=session, segment_index=1
- session.segments.count() == 2

TEST: Recordings ordered by segment_index
- Create recordings with index 2, 0, 1
- session.segments.order_by('segment_index') returns in order

TEST: Session segment_count property
- session.segment_count returns correct count

TEST: Session total_duration_ms property
- Create recordings with duration_ms=60000, 90000
- session.total_duration_ms == 150000

TEST: Session delete cascades to recordings
- Delete session → all segment recordings deleted

TEST: Standalone recording (no session)
- Recording with session=null, segment_index=null is valid
- For simple single-file uploads
```

---

### 10. Recording Session Fields (Updated Model)

#### 10.1 New Recording Fields

```
TEST: Recording with session FK
- Create recording with session reference
- recording.session → RecordingSession object
- segment_index stored correctly

TEST: Recording track_type field
- Default is 'mixed'
- Can set to 'microphone', 'system', 'speaker_sample'

TEST: Recording is_voice_sample flag
- Default is False
- When True, typically track_type='speaker_sample'

TEST: Multi-track session
- Create session
- Add recording with track_type='microphone'
- Add recording with track_type='system'
- Both linked to same session, different tracks
```

#### 10.2 Segment Naming Convention

```
TEST: Segment index is 0-based
- part-01 in filename = segment_index=0
- part-02 in filename = segment_index=1

TEST: Recordings in session can have same segment_index
- Different track_types can share segment_index
- e.g., segment_index=0, track_type='microphone'
- and segment_index=0, track_type='system'
```

---

### 11. SpeakerAnchor Model (Voice Prints)

#### 11.1 Anchor Creation

```
TEST: Create session-scoped anchor
- SpeakerAnchor.objects.create(
    session=session,
    speaker_label="Mark"
  )
- group is null, session is not null
- Constraint passes

TEST: Create group-scoped anchor
- SpeakerAnchor.objects.create(
    group=group,
    speaker_label="Mark"
  )
- session is null, group is not null
- Can be used across multiple sessions

TEST: Anchor requires scope (constraint)
- Try to create anchor with session=null AND group=null
- Should raise IntegrityError (CheckConstraint violation)

TEST: Anchor with both scopes
- Create with session AND group both set
- Should work (constraint is OR, not XOR)
```

#### 11.2 Anchor Identity Linking

```
TEST: Link anchor to Mixtape user
- Create anchor with user=authenticated_user
- anchor.user → User object

TEST: User deletion preserves anchor
- Create anchor linked to user
- Delete user
- anchor.user is null (SET_NULL)
- anchor.speaker_label still intact

TEST: Anchor without user link
- Create anchor with user=null
- speaker_label is only identifier
```

#### 11.3 Voice Sample Reference

```
TEST: Link anchor to source recording
- Create recording with is_voice_sample=True
- Create SpeakerAnchor with source_recording=recording
- sample_start_ms=0, sample_end_ms=15000 (15 sec sample)
- anchor.source_recording → Recording

TEST: Recording deletion preserves anchor
- Delete source_recording
- anchor.source_recording is null (SET_NULL)
- Embedding data still intact

TEST: Sample timing validation
- sample_start_ms < sample_end_ms (application logic)
- Both can be null if embedding generated externally
```

#### 11.4 Embedding Storage

```
TEST: Store binary embedding
- embedding = bytes([0x01, 0x02, ...])  # Vector data
- embedding_model = "pyannote-3.0"
- anchor.save() → embedding stored correctly

TEST: Retrieve embedding
- Load anchor from DB
- anchor.embedding returns exact bytes stored

TEST: Embedding can be null
- Anchor valid without embedding (e.g., manual label only)
```

#### 11.5 Confidence & Status

```
TEST: Confidence score range
- confidence_score=0.95 → valid
- confidence_score=0.0 → valid
- confidence_score can be null

TEST: Anchor active/inactive
- is_active defaults to True
- Set is_active=False → excluded from matching (application logic)
```

---

### 12. Transcription Model

#### 12.1 Transcription CRUD

```
TEST: Create transcription for recording
- Transcription.objects.create(
    recording=recording,
    text="Hello, this is a test.",
    language="en",
    whisper_model="large-v3"
  )
- version defaults to 1

TEST: Transcription requires recording
- Try to create without recording → IntegrityError

TEST: Recording deletion cascades to transcriptions
- Delete recording → all transcriptions deleted
```

#### 12.2 Versioning

```
TEST: Multiple versions per recording
- Create transcription v1 for recording
- Create transcription v2 for recording
- recording.transcriptions.count() == 2

TEST: Version uniqueness constraint
- Create transcription with recording=R, version=1
- Try to create another with same recording=R, version=1
- Should raise IntegrityError (unique_together)

TEST: Re-transcription workflow
- Create v1, set whisper_model="small"
- Create v2, set whisper_model="large-v3"
- Both coexist, v2 is the "current" by convention
```

#### 12.3 Transcription Metadata

```
TEST: Processing timestamps
- Set processing_started_at before Whisper runs
- Set processing_completed_at after Whisper completes
- processing_completed_at > processing_started_at

TEST: Confidence average
- Set confidence_avg=0.87
- Value stored and retrieved correctly

TEST: Language detection
- language="en" for English
- Can be empty if not detected
```

---

### 13. TranscriptSegment Model

#### 13.1 Segment CRUD

```
TEST: Create segment
- TranscriptSegment.objects.create(
    transcription=transcription,
    segment_index=0,
    start_ms=0,
    end_ms=5000,
    text="Hello, this is Mark."
  )
- All fields stored correctly

TEST: Segment requires transcription
- Try to create without transcription → IntegrityError

TEST: Transcription deletion cascades to segments
- Delete transcription → all segments deleted
```

#### 13.2 Segment Ordering

```
TEST: Segments ordered by index
- Create segments with index 2, 0, 1
- transcription.segments.all() returns in order [0, 1, 2]

TEST: segment_index is required
- Try to create without segment_index → error
```

#### 13.3 Timing

```
TEST: Start and end timing
- start_ms=5000, end_ms=10000
- segment.duration_ms property returns 5000

TEST: Timing validation (application layer)
- start_ms < end_ms should be enforced by application
- Segments should not overlap (application logic)
```

#### 13.4 Speaker Attribution

```
TEST: Segment with speaker anchor
- Create SpeakerAnchor for "Mark"
- Create segment with speaker_anchor=anchor
- speaker_label="Mark" (copied from anchor)
- speaker_confidence=0.92

TEST: Segment without speaker anchor
- speaker_anchor=null
- speaker_label="Speaker A" (fallback)
- speaker_confidence=null or low

TEST: Speaker anchor deletion preserves segment
- Delete speaker_anchor
- segment.speaker_anchor is null (SET_NULL)
- segment.speaker_label still "Mark"

TEST: Update speaker attribution
- Initially speaker_label="Speaker A"
- Link to SpeakerAnchor later
- Update speaker_label to match anchor
```

#### 13.5 Confidence

```
TEST: Transcription confidence
- confidence=0.95 → segment was clear
- confidence=0.45 → segment was unclear (crosstalk/noise)
- confidence can be null
```

---

### 14. Integration Tests

#### 14.1 Full Session Workflow

```
TEST: Complete session with segments and transcriptions
1. Create RecordingSession for group
2. Create Recording segment_index=0, upload audio
3. Create Recording segment_index=1, upload audio
4. Create Transcription for each recording
5. Create TranscriptSegments for each transcription
6. Verify session.segments, recording.transcriptions, transcription.segments

TEST: Session with voice samples
1. Create RecordingSession
2. Create Recording with is_voice_sample=True for "Mark"
3. Create SpeakerAnchor linked to that recording
4. Create main Recording segments
5. Create Transcriptions with speaker attribution
6. Verify segments have speaker_label="Mark" with confidence
```

#### 14.2 Sponsor Consistency

```
TEST: Session and recordings share sponsor
- Create session for group A
- Create recording with session reference
- recording.sponsor should be group A (inherited or set)

TEST: Anchor group matches session sponsor
- Create group-scoped anchor for group A
- Use in session sponsored by group A
- Should work correctly
```

#### 14.3 Edge Cases

```
TEST: Empty transcription
- Transcription with text="" is valid
- No segments required

TEST: Very long segment text
- text with 10000+ characters → stored correctly

TEST: Unicode in speaker labels
- speaker_label="田中太郎" → stored correctly
- speaker_label with emoji → stored correctly

TEST: Concurrent transcription versions
- Create v1 and v2 simultaneously
- Both should succeed with different versions
```

---

### 15. Fixtures for New Models

```python
@pytest.fixture
def test_session(db, test_group, authenticated_user):
    """Create a test recording session"""
    from concord.models import RecordingSession, SessionStatus
    from django.contrib.contenttypes.models import ContentType

    return RecordingSession.objects.create(
        sponsor_content_type=ContentType.objects.get_for_model(test_group),
        sponsor_object_id=test_group.id,
        title="Test Session",
        submitted_by=authenticated_user,
        status=SessionStatus.RECORDING,
        segment_duration_seconds=900
    )

@pytest.fixture
def test_session_recording(db, test_session, authenticated_user):
    """Create a test recording within a session"""
    from concord.models import Recording, RecordingStatus, TrackType
    from django.contrib.contenttypes.models import ContentType

    return Recording.objects.create(
        sponsor_content_type=test_session.sponsor_content_type,
        sponsor_object_id=test_session.sponsor_object_id,
        session=test_session,
        segment_index=0,
        track_type=TrackType.MIXED,
        title="Session Segment 1",
        submitted_by=authenticated_user,
        status=RecordingStatus.UPLOADED
    )

@pytest.fixture
def test_speaker_anchor(db, test_session, authenticated_user):
    """Create a test speaker anchor"""
    from concord.models import SpeakerAnchor

    return SpeakerAnchor.objects.create(
        session=test_session,
        speaker_label="Test Speaker",
        user=authenticated_user,
        confidence_score=0.95,
        is_active=True
    )

@pytest.fixture
def test_transcription(db, test_session_recording):
    """Create a test transcription"""
    from concord.models import Transcription

    return Transcription.objects.create(
        recording=test_session_recording,
        version=1,
        text="Hello, this is a test transcription.",
        language="en",
        whisper_model="large-v3"
    )

@pytest.fixture
def test_transcript_segment(db, test_transcription, test_speaker_anchor):
    """Create a test transcript segment"""
    from concord.models import TranscriptSegment

    return TranscriptSegment.objects.create(
        transcription=test_transcription,
        segment_index=0,
        start_ms=0,
        end_ms=5000,
        text="Hello, this is a test.",
        speaker_anchor=test_speaker_anchor,
        speaker_label="Test Speaker",
        speaker_confidence=0.92
    )
```

---

## Test Data Setup

### Prerequisites
1. Test user with authentication token
2. Test group with known slug and ID
3. Sample audio files:
   - `test.mp3` (small, ~100KB)
   - `test.wav` (medium, ~1MB)
   - `large.mp3` (large, ~50MB)
   - `invalid.txt` (non-audio)

### Fixtures
```python
# Suggested pytest fixtures

@pytest.fixture
def test_group(db):
    """Create a test group"""
    from groups.models import Group
    return Group.objects.create(
        title="Test Group",
        slug="test-group"
    )

@pytest.fixture
def test_recording(db, test_group, authenticated_user):
    """Create a test recording"""
    from concord.models import Recording, RecordingStatus
    from django.contrib.contenttypes.models import ContentType

    return Recording.objects.create(
        sponsor_content_type=ContentType.objects.get_for_model(test_group),
        sponsor_object_id=test_group.id,
        title="Test Recording",
        submitted_by=authenticated_user,
        status=RecordingStatus.UPLOADED
    )

@pytest.fixture
def audio_file():
    """Create a test audio file"""
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        "test.mp3",
        b"fake audio content",
        content_type="audio/mpeg"
    )
```

---

## Notes for Nick

1. **BaseContent inheritance**: Recording uses the same sponsor pattern as Library, WritingPiece, etc. If you have existing tests for those, the sponsor-related tests should be similar.

2. **Status machine**: The transition logic is in `Recording.transition_to()`. Invalid transitions raise `ValueError`.

3. **File storage**: Currently uses Django's `default_storage`. In production this is S3. Tests may need to mock storage or use local filesystem.

4. **No permission checks yet**: The API only checks authentication, not group membership. This is a known gap for Phase 2.

5. **Soft delete**: DELETE doesn't remove the record, just sets status='archived'.

---

## Questions / Clarifications Needed

- [ ] Should archived recordings be excluded from list by default?
- [ ] Should we add rate limiting on upload endpoint?
- [ ] Permission model: who can create/view/edit recordings for a group?
- [ ] Should status transitions be logged for audit trail?

---

*Test plan generated for handoff. Please reach out to Mark with questions.*

---

## Phase 4: Whisper Integration

The following tests cover the Whisper transcription service and Celery background tasks.

---

### 16. Transcription Trigger API

#### 16.1 Trigger Endpoint

```
TEST: Trigger transcription for recording
- POST /api/concord/recordings/{id}/transcribe/
- Response: 200 with { task_id, status: "queued" }

TEST: Trigger with custom model
- POST /api/concord/recordings/{id}/transcribe/
  Body: { model: "large-v3" }
- Response: 200, task queued with specified model

TEST: Trigger with language hint
- POST /api/concord/recordings/{id}/transcribe/
  Body: { language: "en" }
- Response: 200, task queued with language

TEST: Trigger for non-existent recording
- POST /api/concord/recordings/{fake-uuid}/transcribe/ → 404

TEST: Trigger requires authentication
- POST without auth → 401

TEST: Trigger for recording without audio
- Create recording without file upload
- POST /transcribe/ → 400 "No audio file"
```

#### 16.2 Model Validation

```
TEST: Valid model names accepted
- tiny, base, small, medium, large, large-v2, large-v3 → 200

TEST: Invalid model name rejected
- Body: { model: "invalid-model" } → 400 "Invalid model"
```

---

### 17. Whisper Service (Unit Tests)

#### 17.1 Backend Detection

```
TEST: faster-whisper detected when installed
- Mock faster_whisper import success
- service._detect_backend() → "faster-whisper"

TEST: openai-api detected as fallback
- Mock faster_whisper import failure
- Mock OPENAI_API_KEY set
- service._detect_backend() → "openai-api"

TEST: local whisper as last resort
- Mock faster_whisper failure
- Mock no OPENAI_API_KEY
- Mock whisper import success
- service._detect_backend() → "whisper"

TEST: ImportError when no backend available
- Mock all imports fail
- service._detect_backend() raises ImportError
```

#### 17.2 Transcription Result

```
TEST: TranscriptionResult dataclass
- result = TranscriptionResult(text="Hello", language="en")
- result.text == "Hello"
- result.segments == [] (default)
- result.confidence_avg == 0.0 (default)

TEST: TranscriptSegment dataclass
- segment = TranscriptSegment(start_ms=0, end_ms=5000, text="Hello")
- segment.confidence == 0.0 (default)
- segment.speaker_id is None (default)
```

#### 17.3 Audio File Handling

```
TEST: transcribe_audio with local file
- Provide existing local audio path
- Returns TranscriptionResult

TEST: transcribe_audio with storage path
- Provide path starting with "recordings/"
- Service downloads from storage
- Temp file created and cleaned up

TEST: transcribe_audio file not found
- Provide non-existent path
- Raises FileNotFoundError

TEST: transcribe_recording by ID
- Provide valid recording_id with audio_path
- Returns TranscriptionResult
- Uses recording's audio file

TEST: transcribe_recording without audio
- Provide recording_id with no audio_path
- Raises FileNotFoundError "No audio file for recording"
```

---

### 18. Celery Transcription Task

#### 18.1 Task Execution

```
TEST: transcribe_recording_task success
- Create recording with audio file
- Call transcribe_recording_task(recording_id)
- Recording status transitions: uploaded → transcribing → ready
- Transcription record created
- TranscriptSegments created

TEST: Task returns result dict
- result = transcribe_recording_task(recording_id)
- result["status"] == "success"
- result["transcription_id"] is valid UUID
- result["segment_count"] > 0
- result["language"] is set
```

#### 18.2 Status Transitions

```
TEST: Task sets transcribing status
- Initial status: uploaded
- During task: status == transcribing
- processing_started_at is set

TEST: Task sets ready status on success
- After task completes: status == ready
- processing_completed_at is set

TEST: Task sets failed status on error
- Mock transcription to fail
- status == failed
- processing_error contains message
```

#### 18.3 Transcription Record Creation

```
TEST: Creates Transcription record
- Transcription.objects.filter(recording=recording).exists()
- transcription.text is not empty
- transcription.language detected
- transcription.whisper_model matches requested

TEST: Version incrementing
- Run task twice on same recording
- First creates version=1
- Second creates version=2

TEST: Creates TranscriptSegments
- transcription.segments.count() > 0
- Segments have start_ms, end_ms, text
- Segments ordered by segment_index
```

#### 18.4 Error Handling

```
TEST: Recording not found
- Call task with fake UUID
- Returns { status: "error", error: "Recording not found" }

TEST: Already transcribing (skip)
- Set recording.status = transcribing
- Call task
- Returns { status: "skipped", reason: "already_transcribing" }

TEST: Already has transcription (skip)
- Create existing transcription
- Set status to ready
- Call task
- Returns { status: "skipped", reason: "already_transcribed" }

TEST: Whisper not installed
- Mock transcription to raise ImportError
- Recording marked as failed
- Returns { status: "error", error: "Whisper not installed" }

TEST: Audio file missing
- Recording exists but file doesn't
- Recording marked as failed
- Returns { status: "error", error: file path }
```

#### 18.5 Retry Logic

```
TEST: Task retries on failure
- Mock transcription to fail
- Task should retry (up to 3 times)
- Exponential backoff: 30s, 60s, 120s

TEST: Max retries exceeded
- Mock all attempts fail
- After 3 retries, returns error
- Recording status == failed
```

---

### 19. Periodic Transcription Task

#### 19.1 transcribe_pending_recordings

```
TEST: Finds uploaded recordings
- Create 3 recordings with status=uploaded and audio_path
- Call transcribe_pending_recordings()
- All 3 queued for transcription

TEST: Skips recordings without audio
- Create recording without audio_path
- Not queued

TEST: Skips already transcribed
- Create recording with existing transcription
- Not queued

TEST: Respects limit parameter
- Create 10 recordings
- Call with limit=5
- Only 5 queued

TEST: Returns stats
- result = transcribe_pending_recordings()
- result["queued_count"] == N
- result["skipped_count"] == N
```

---

### 20. Integration: Full Transcription Flow

```
TEST: End-to-end transcription
1. Create group recording
2. Upload audio file (POST /upload/)
3. Trigger transcription (POST /transcribe/)
4. Wait for task completion (poll status)
5. GET /recordings/{id}/ → status == ready
6. GET /recordings/{id}/transcriptions/ → has transcription
7. Transcription has text, language, segments

TEST: Session with multiple segments
1. Create RecordingSession
2. Create Recording segment_index=0, upload audio
3. Create Recording segment_index=1, upload audio
4. Trigger transcription for both
5. Both have Transcription records
6. Session.segments all have status=ready
```

---

### 21. Whisper Model-Specific Tests

```
TEST: base model (default)
- Fast, lower accuracy
- Good for testing

TEST: large-v3 model
- Slow, high accuracy
- Requires more memory

TEST: Language auto-detection
- English audio → language="en"
- Spanish audio → language="es"

TEST: Language hint respected
- Provide language="en"
- Transcription uses English model
```

---

### 22. Fixtures for Phase 4

```python
@pytest.fixture
def recording_with_audio(db, test_group, authenticated_user, tmp_path):
    """Create a recording with actual audio file"""
    from concord.models import Recording, RecordingStatus
    from django.contrib.contenttypes.models import ContentType
    from django.core.files.storage import default_storage
    import os

    recording = Recording.objects.create(
        sponsor_content_type=ContentType.objects.get_for_model(test_group),
        sponsor_object_id=test_group.id,
        title="Recording with Audio",
        submitted_by=authenticated_user,
        status=RecordingStatus.UPLOADED
    )

    # Create a small test audio file (or use fixture audio)
    audio_path = f"recordings/group/{test_group.id}/{recording.id}/test.mp3"
    # ... save audio content to storage ...
    recording.audio_path = audio_path
    recording.save()

    return recording


@pytest.fixture
def mock_whisper_service(mocker):
    """Mock WhisperService for fast tests"""
    from concord.services.whisper import TranscriptionResult, TranscriptSegment

    mock_result = TranscriptionResult(
        text="This is a test transcription.",
        language="en",
        segments=[
            TranscriptSegment(start_ms=0, end_ms=3000, text="This is a test", confidence=0.95),
            TranscriptSegment(start_ms=3000, end_ms=5000, text="transcription.", confidence=0.92),
        ],
        confidence_avg=0.935,
        model_name="base",
        duration_ms=5000,
    )

    mocker.patch(
        'concord.services.whisper.transcribe_recording',
        return_value=mock_result
    )
    return mock_result


@pytest.fixture
def celery_eager_mode(settings):
    """Run Celery tasks synchronously for testing"""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
```

---

### 23. Notes for Nick (Phase 4)

1. **Whisper backends**: The service supports faster-whisper, OpenAI API, and local whisper. For unit tests, mock the transcription function. For integration tests, you may need faster-whisper installed or use the OpenAI API with a key.

2. **Celery testing**: Use `celery_eager_mode` fixture to run tasks synchronously in tests. For async tests, use Celery's test helpers or redis/rabbitmq mock.

3. **Audio files**: Tests need actual audio files for integration tests. Consider:
   - Small fixture files checked into repo
   - Generated silence/tone for minimal tests
   - Real sample files for accuracy tests

4. **Task retries**: To test retry logic, mock failures and verify exponential backoff. The task uses `bind=True` so `self.request.retries` tracks attempt count.

5. **Processing time**: Large models (large-v3) can take significant time. Set appropriate timeouts in tests or use smaller models.

---

## Questions / Clarifications Needed (Phase 4)

- [ ] Should transcription be auto-triggered on upload?
- [ ] Default Whisper model for production vs development?
- [ ] Rate limiting on transcribe endpoint?
- [ ] Should we store Whisper model version with transcription?
- [ ] Webhook/callback when transcription completes?
