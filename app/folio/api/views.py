# folio/api/views.py

import time
import uuid

from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.text import get_valid_filename
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import StoredFile
from inkwell.client import InkwellUnavailableError

from folio.models import (
    CandidateStatus,
    Folio,
    FolioInception,
    FolioMaterialCandidate,
    FolioNote,
    FolioNoteSource,
    FolioNoteStatus,
)
from folio.services.gate1_parse import parse_gate1
from folio.services.gate2_extract import extract_gate2
from folio.services.gate3_classify import classify_gate3
from folio.services.gate4_normalize import build_candidates, derive_title
from folio.services.gate5_validate import validate_candidates
from folio.services.note_search import search_folio_notes
from folio.shapes import Shape
from folio.tasks import tend_folio_note_task, transcribe_folio_note_task
from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
from stackroom_client import StackroomClientError
from .serializers import (
    FolioCreateSerializer,
    FolioInceptionCreateSerializer,
    FolioInceptionSerializer,
    FolioMaterialCandidatePatchSerializer,
    FolioMaterialCandidateSerializer,
    FolioNoteSerializer,
    FolioNoteShapePatchSerializer,
    FolioNoteTextCreateSerializer,
    FolioSerializer,
    FolioTitlePatchSerializer,
)

# Same limits as Notebook voice Seeds (writing.api.views).
MAX_FOLIO_NOTE_AUDIO_BYTES = 20 * 1024 * 1024  # 20MB
ALLOWED_AUDIO_PREFIXES = ("audio/",)
ALLOWED_AUDIO_MIME = ("video/webm",)


class FolioInceptionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = FolioInceptionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        raw_text = serializer.validated_data["raw_text"]
        title = serializer.validated_data.get("title", "")

        with transaction.atomic():
            folio = Folio.objects.create(title=title, created_by=request.user)
            inception = FolioInception.objects.create(
                folio=folio,
                raw_text=raw_text,
                created_by=request.user,
            )

        return Response(
            FolioInceptionSerializer(inception).data,
            status=status.HTTP_201_CREATED,
        )


class FolioInceptionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, inception_id):
        inception = get_object_or_404(
            FolioInception.objects.select_related("folio"),
            pk=inception_id,
            folio__created_by=request.user,
        )
        return Response(FolioInceptionSerializer(inception).data)


class FolioInceptionAnalyzeView(APIView):
    """
    Runs the Hildegard pipeline. Phase 4 adds Gate 4 (deterministic display
    normalization) and Gate 5 (deterministic validation) on top of Gates
    1-3 — validated candidates are persisted as FolioMaterialCandidate rows
    with status=proposed, never confirmed automatically (prototype spec
    §8). Re-running analyze replaces only proposed candidates for this
    inception; anything a human has already confirmed/rejected/amended is
    left untouched, per the build plan guardrail that confirmed status is
    durable. Debug trace (prototype spec §12) is prototype instrumentation,
    not permanent product data — not persisted, only returned in the
    response.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, inception_id):
        inception = get_object_or_404(
            FolioInception,
            pk=inception_id,
            folio__created_by=request.user,
        )

        start = time.monotonic()
        gate1_output = parse_gate1(inception.raw_text)
        gate1_latency_ms = round((time.monotonic() - start) * 1000, 2)

        gate2_output = None
        gate2_error = None
        start = time.monotonic()
        try:
            gate2_output = extract_gate2(inception.raw_text)
        except InkwellUnavailableError as exc:
            gate2_error = str(exc)
        gate2_latency_ms = round((time.monotonic() - start) * 1000, 2)

        gate3_output = None
        gate3_error = None
        start = time.monotonic()
        try:
            gate3_output = classify_gate3(inception.raw_text, gate1_output)
        except InkwellUnavailableError as exc:
            gate3_error = str(exc)
        gate3_latency_ms = round((time.monotonic() - start) * 1000, 2)

        # Gate 3 failing to run (Inkwell unreachable) means this pass has no
        # trustworthy view of materiality — leave any previously persisted
        # proposed candidates untouched rather than replacing them with an
        # empty set. A transient outage must not look like "nothing found".
        persisted_count = None
        gate4_5_errors = []
        gate4_5_warnings = []
        gate4_5_latency_ms = 0.0
        if gate3_output is not None:
            start = time.monotonic()
            raw_candidates = build_candidates(inception.raw_text, gate2_output, gate3_output)
            validation = validate_candidates(inception.raw_text, raw_candidates, gate1_output)
            gate4_5_errors = validation["errors"]
            gate4_5_warnings = validation["warnings"]

            with transaction.atomic():
                FolioMaterialCandidate.objects.filter(
                    inception=inception, status=CandidateStatus.PROPOSED
                ).delete()
                new_candidates = [
                    FolioMaterialCandidate(inception=inception, status=CandidateStatus.PROPOSED, **candidate)
                    for candidate in validation["valid_candidates"]
                ]
                if new_candidates:
                    FolioMaterialCandidate.objects.bulk_create(new_candidates)
                persisted_count = len(new_candidates)

                # Near-verbatim short form only (spec section 8) -- never
                # overwrites a title a human has already set.
                if not inception.folio.title:
                    derived_title = derive_title(validation["valid_candidates"])
                    if derived_title:
                        Folio.objects.filter(pk=inception.folio_id).update(title=derived_title)
            gate4_5_latency_ms = round((time.monotonic() - start) * 1000, 2)

        if gate3_output is not None:
            status_value = "gate_5_complete"
        elif gate2_output is not None:
            status_value = "gate_3_unavailable"
        else:
            status_value = "gate_2_unavailable"
        payload = {"inception_id": str(inception.id), "status": status_value}

        is_dev = request.user.is_staff or request.user.is_superuser
        if request.query_params.get("debug") == "1" and is_dev:
            payload["debug"] = {
                "gate_1": {
                    "output": gate1_output,
                    "latency_ms": gate1_latency_ms,
                },
                "gate_2": {
                    "output": gate2_output,
                    "error": gate2_error,
                    "latency_ms": gate2_latency_ms,
                },
                "gate_3": {
                    "output": gate3_output,
                    "error": gate3_error,
                    "latency_ms": gate3_latency_ms,
                },
                "gate_4_5": {
                    "candidates_persisted": persisted_count,
                    "skipped": gate3_output is None,
                    "errors": gate4_5_errors,
                    "warnings": gate4_5_warnings,
                    "latency_ms": gate4_5_latency_ms,
                },
            }

        return Response(payload)


class FolioTitleDetailView(APIView):
    """Lets the writer edit the Folio title, per prototype spec section 6."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, folio_id):
        folio = get_object_or_404(Folio, pk=folio_id, created_by=request.user)
        serializer = FolioTitlePatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        folio.title = serializer.validated_data["title"]
        folio.save(update_fields=["title", "updated_at"])
        return Response({"id": str(folio.id), "title": folio.title})


def _get_owned_candidate(request, candidate_id):
    return get_object_or_404(
        FolioMaterialCandidate,
        pk=candidate_id,
        inception__folio__created_by=request.user,
    )


class FolioMaterialCandidateDetailView(APIView):
    """
    Lets the writer edit a candidate's display text, per prototype spec
    section 6 ("amend the visible intention", "edit a material item's
    display text"). source_text and the source span are never editable —
    they are Hildegard's verbatim record of what it found in raw_text,
    per the build plan guardrail on preserving provenance. Editing marks
    the candidate amended regardless of its prior status, since a human
    has now touched it.
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, candidate_id):
        candidate = _get_owned_candidate(request, candidate_id)
        serializer = FolioMaterialCandidatePatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        candidate.display_text = serializer.validated_data["display_text"]
        candidate.status = CandidateStatus.AMENDED
        candidate.save(update_fields=["display_text", "status", "updated_at"])
        return Response(FolioMaterialCandidateSerializer(candidate).data)


class FolioMaterialCandidateConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, candidate_id):
        candidate = _get_owned_candidate(request, candidate_id)
        candidate.status = CandidateStatus.CONFIRMED
        candidate.save(update_fields=["status", "updated_at"])
        return Response(FolioMaterialCandidateSerializer(candidate).data)


class FolioMaterialCandidateRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, candidate_id):
        candidate = _get_owned_candidate(request, candidate_id)
        candidate.status = CandidateStatus.REJECTED
        candidate.save(update_fields=["status", "updated_at"])
        return Response(FolioMaterialCandidateSerializer(candidate).data)


# ---------------------------------------------------------------------------
# Folio Notes PoC (puddlejump/decisions/folio/folio-notes-poc-mobile-handoff.md)
# ---------------------------------------------------------------------------


class FolioListCreateView(APIView):
    """
    GET  /folios -> the writer's Folios, for Folio selection on the Notes surface.
    POST /folios -> a bare Folio (title only), so Notes capture doesn't require
                    going through an Inception first.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        folios = Folio.objects.filter(created_by=request.user).order_by("-updated_at")
        return Response(FolioSerializer(folios, many=True).data)

    def post(self, request):
        serializer = FolioCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        folio = Folio.objects.create(title=serializer.validated_data["title"], created_by=request.user)
        return Response(FolioSerializer(folio).data, status=status.HTTP_201_CREATED)


class FolioNoteListCreateView(APIView):
    """
    GET  /folios/<id>/notes -> recent FolioNotes, newest first.
    POST /folios/<id>/notes -> capture. Multipart with `audio_file` for voice,
         or JSON/form `raw_text` for text. Persists immediately and returns
         without waiting on any model work (build plan §4.2, §45): voice notes
         come back `processing` with transcription enqueued; text notes come
         back `ready`.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, folio_id):
        folio = get_object_or_404(Folio, pk=folio_id, created_by=request.user)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 50)), 200))
        except ValueError:
            limit = 50
        notes = folio.notes.order_by("-created_at")[:limit]
        return Response(FolioNoteSerializer(notes, many=True).data)

    def post(self, request, folio_id):
        folio = get_object_or_404(Folio, pk=folio_id, created_by=request.user)
        audio_file = request.FILES.get("audio_file")
        if audio_file:
            return self._create_voice_note(request, folio, audio_file)

        serializer = FolioNoteTextCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        note = FolioNote.objects.create(
            folio=folio,
            created_by=request.user,
            source_type=FolioNoteSource.TEXT,
            raw_text=serializer.validated_data["raw_text"],
            status=FolioNoteStatus.READY,
            source=serializer.validated_data["source"],
        )
        tend_folio_note_task.delay(str(note.id))
        enqueue_stackroom_ingest(note, reason="folio_note_captured")
        return Response(FolioNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    def _create_voice_note(self, request, folio, audio_file):
        if audio_file.size > MAX_FOLIO_NOTE_AUDIO_BYTES:
            return Response(
                {"detail": f"Audio file too large (max {MAX_FOLIO_NOTE_AUDIO_BYTES // (1024 * 1024)}MB)."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        content_type = (audio_file.content_type or "").lower()
        if not (content_type.startswith(ALLOWED_AUDIO_PREFIXES) or content_type in ALLOWED_AUDIO_MIME):
            return Response(
                {"detail": f"Unsupported audio type: {content_type or 'unknown'}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base = get_valid_filename(audio_file.name or "")
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())
        s3_key = f"folio/notes/audio/{request.user.id}/{unique}"

        audio_file.seek(0)
        saved_key = default_storage.save(s3_key, audio_file)
        source = (request.data.get("source") or "")[:32]

        with transaction.atomic():
            stored = StoredFile.objects.create(
                file_path=saved_key,
                file_name=audio_file.name or "",
                file_type=audio_file.content_type or "",
                file_size=audio_file.size or 0,
                uploaded_by=request.user,
                source=source or "web",
            )
            note = FolioNote.objects.create(
                folio=folio,
                created_by=request.user,
                source_type=FolioNoteSource.VOICE,
                audio_file=stored,
                status=FolioNoteStatus.PROCESSING,
                source=source,
            )

        transcribe_folio_note_task.delay(str(note.id))
        return Response(FolioNoteSerializer(note).data, status=status.HTTP_201_CREATED)


class FolioNoteSearchView(APIView):
    """
    GET /folios/<id>/notes/search -> Folio Notes retrieval (PoC Phase 4).
        q       semantic query via Stackroom; omitted -> most recent first
        shape   effective Shape (confirmed, else suggested, else unplaced)
        entity  a writer-confirmed Entity id among the note's mentions
        limit   1-100, default 20
    Each result is a FolioNote plus `score` (null when not semantic).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, folio_id):
        folio = get_object_or_404(Folio, pk=folio_id, created_by=request.user)
        params = request.query_params
        query = (params.get("q") or "").strip()
        shape = params.get("shape") or None
        if shape and shape not in Shape.values:
            return Response({"shape": [f"Unknown Shape: {shape}"]}, status=status.HTTP_400_BAD_REQUEST)
        entity_id = params.get("entity") or None
        if entity_id:
            try:
                entity_id = str(uuid.UUID(entity_id))
            except ValueError:
                return Response({"entity": ["Must be a UUID."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = max(1, min(int(params.get("limit", 20)), 100))
        except ValueError:
            limit = 20

        try:
            hits = search_folio_notes(
                folio, user=request.user, query=query, shape=shape, entity_id=entity_id, limit=limit
            )
        except StackroomClientError as exc:
            return Response(
                {"detail": "Search is unavailable right now.", "error": exc.detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        results = []
        for hit in hits:
            data = FolioNoteSerializer(hit.note).data
            data["score"] = hit.score
            results.append(data)
        return Response({"mode": "semantic" if query else "recent", "results": results})


class FolioNoteDetailView(APIView):
    """
    PATCH /folios/<id>/notes/<note_id> -> one-tap Shape correction. Sets only
    confirmed_shape; the model's suggested_shape is kept for provenance and
    correction-rate evaluation (build plan §12, §40).
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, folio_id, note_id):
        note = get_object_or_404(FolioNote, pk=note_id, folio_id=folio_id, folio__created_by=request.user)
        serializer = FolioNoteShapePatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        note.confirmed_shape = serializer.validated_data["confirmed_shape"]
        note.save(update_fields=["confirmed_shape", "updated_at"])
        return Response(FolioNoteSerializer(note).data)
