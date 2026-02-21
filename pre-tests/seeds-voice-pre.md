# Voice Seeds v1 Backend Test Plan

Scope: Validate `Seed` voice capture backend (audio upload + transcription + status flow).

Endpoints:
- `POST /api/writing/seeds` (multipart for voice)
- `GET /api/writing/seeds`
- `GET /api/writing/seeds/<id>`

Assumptions:
- Authenticated user `u1` exists.
- Celery worker running for transcription tasks.
- Whisper backend available (faster‑whisper or local).

---

## A) Audio upload + seed creation

### A1. Create voice seed (multipart)
Steps:
1) POST `/api/writing/seeds` with `multipart/form-data`:
   - `audio_file`: short audio file (<= 20MB)
   - `kind=voice`
   - `source=web`
Expected:
- `201`
- Response includes:
  - `kind = "voice"`
  - `status = "processing"`
  - `audio_file` (id) + `audio_url`
  - `body_text` empty or missing

### A2. Reject oversize file
Steps:
1) POST `/api/writing/seeds` with file > 20MB.
Expected:
- `413` with “Audio file too large”.

### A3. Reject non-audio
Steps:
1) POST `/api/writing/seeds` with a non‑audio MIME type.
Expected:
- `400` with unsupported type error.

---

## B) Transcription flow

### B1. Processing → Ready
Steps:
1) After A1, poll `GET /api/writing/seeds/<id>` until status updates.
Expected:
- `status` transitions to `ready`
- `transcript_text` populated
- `body_text` populated (matches transcript)
- `transcript_provider = "whisper"`
- `transcript_created_at` set

### B2. Failure handling
Steps:
1) Upload a corrupt audio file or stop the worker.
2) Poll seed.
Expected:
- `status = "failed"`
- `transcript_error` populated

---

## C) List behavior

### C1. Voice seeds appear in list even with empty body_text
Steps:
1) Immediately after A1, call `GET /api/writing/seeds`.
Expected:
- Seed appears even though `body_text` empty (status processing).

### C2. Mixed list rendering
Steps:
1) Create a normal text seed.
2) Verify list includes both voice + text seeds.

---

## D) Regression checks

### D1. Text seed create still works
Steps:
1) POST `/api/writing/seeds` JSON with `body_text`.
Expected:
- `201`, `kind="text"`, `status="ready"`.

---

## Deliverables
- Response JSON for A1 and B1.
- Confirmation of transcription status transition.
- Error response for A2 or A3.
