# folio/tasks.py
#
# Folio Notes PoC — background work for FolioNotes, all after the note is
# already persisted (build plan §4.2):
#
#   transcribe_folio_note_task — voice notes; mirrors writing.tasks.transcribe_seed_task.
#   tend_folio_note_task       — records an ActionRun and dispatches the
#                                `folio_note_tend` capability to Switchboard
#                                (→ Inkwell), same pattern as switchboard.classify_async.
#   apply_folio_note_tending   — Switchboard's callback; projects the finished
#                                ActionRun onto the note.
#
# Each step pushes a Livewire event so the mobile list-refetch + socket
# pattern from Notebook picks up changes without the writer waiting.

import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from concord.services.whisper import transcribe_audio
from folio.models import FolioNote, FolioNoteSource, FolioNoteStatus
from folio.shapes import allowed_shapes, coerce_shape
from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus
from mixtape.celery_app import app as celery_app

TENDING_CAPABILITY = "folio_note_tend"
_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_NAMESPACE = "platform:crossroads"

logger = logging.getLogger(__name__)


def _notify(note: FolioNote, event: str) -> None:
    """Push a folio_note:* event to the owner's socket via Livewire /notify. Fire-and-forget."""
    if not note.created_by:
        return
    livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
    secret = getattr(settings, "LIVEWIRE_NOTIFY_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Notify-Secret"] = secret
    try:
        requests.post(
            f"{livewire_url}/notify",
            json={
                "event": event,
                "username": note.created_by.username,
                "payload": {"folio_note_id": str(note.id), "folio_id": str(note.folio_id)},
            },
            headers=headers,
            timeout=3,
        )
    except Exception as exc:
        logger.warning("[folio-notes] Failed to notify livewire (%s): %s", event, exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_folio_note_task(self, note_id: str):
    try:
        note = FolioNote.objects.select_related("created_by", "audio_file").get(id=note_id)
    except FolioNote.DoesNotExist:
        logger.error("[folio-notes] FolioNote %s not found", note_id)
        return {"status": "missing"}

    if note.source_type != FolioNoteSource.VOICE:
        return {"status": "skipped", "reason": "not_voice"}

    if not note.audio_file or not note.audio_file.file_path:
        note.status = FolioNoteStatus.FAILED
        note.transcript_error = "Missing audio file."
        note.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        result = transcribe_audio(note.audio_file.file_path)
        note.transcript_text = (result.text or "").strip()
        note.transcript_model = result.model_name or ""
        note.transcript_backend = result.backend or ""
        note.transcript_created_at = timezone.now()
        note.transcript_error = ""
        note.status = FolioNoteStatus.READY
        note.save(update_fields=[
            "transcript_text",
            "transcript_model",
            "transcript_backend",
            "transcript_created_at",
            "transcript_error",
            "status",
            "updated_at",
        ])
        _notify(note, "folio_note:transcribed")
        if note.transcript_text:
            tend_folio_note_task.delay(str(note.id))
            enqueue_stackroom_ingest(note, reason="folio_note_transcribed")
        return {"status": "ok", "chars": len(note.transcript_text)}
    except Exception as exc:
        # The audio stays on the note — a failed transcription is a
        # recoverable note, never a lost capture (build plan §41).
        logger.error("[folio-notes] Transcription failed for %s: %s", note_id, exc, exc_info=True)
        note.status = FolioNoteStatus.FAILED
        note.transcript_error = str(exc)
        note.save(update_fields=["status", "transcript_error", "updated_at"])
        raise self.retry(exc=exc)


@shared_task(queue="commons")
def tend_folio_note_task(note_id: str):
    """Record an ActionRun and hand tending to Switchboard. Re-running is safe:
    the newest ActionRun becomes the note's tending_action_run, and results
    from any older run are ignored when they arrive."""
    try:
        note = FolioNote.objects.select_related("folio", "created_by").get(id=note_id)
    except FolioNote.DoesNotExist:
        logger.error("[folio-notes] FolioNote %s not found for tending", note_id)
        return {"status": "missing"}

    text = (note.text or "").strip()
    if not text:
        return {"status": "skipped", "reason": "no_text"}

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))
    capability_payload = {
        "source_ref": f"folio_note:{note.id}",
        "source_text": text,
        "allowed_shapes": allowed_shapes(),
        "folio_title": note.folio.title or None,
    }
    principal_user_id = str(note.created_by_id) if note.created_by_id else None

    action_run = ActionRun.objects.create(
        tool_name=f"capability.{TENDING_CAPABILITY}",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.SYSTEM,
        initiator_id=principal_user_id or "",
        request_payload={"folio_note_id": str(note.id), **capability_payload},
    )
    note.tending_action_run = action_run
    note.save(update_fields=["tending_action_run", "updated_at"])

    celery_app.send_task(
        "switchboard.capability_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": principal_user_id,
            "principal_service_token_id": None,
            "capability": TENDING_CAPABILITY,
            "capability_payload": capability_payload,
            "callback_task": "folio.tasks.apply_folio_note_tending",
            "callback_queue": "commons",
        },
        queue="switchboard",
    )
    return {"status": "dispatched", "action_run_id": str(action_run.id)}


@shared_task(queue="commons")
def apply_folio_note_tending(action_run_id: str):
    """Switchboard callback. Writes only model-derived fields — confirmed_shape
    and the raw capture are never touched (build plan §4.3, §12). A failed run
    leaves the note exactly as it was, i.e. still a fully usable capture (§41)."""
    try:
        action_run = ActionRun.objects.get(id=action_run_id)
    except ActionRun.DoesNotExist:
        logger.error("[folio-notes] ActionRun %s not found for tending callback", action_run_id)
        return {"status": "missing"}

    note = FolioNote.objects.select_related("created_by").filter(tending_action_run_id=action_run.id).first()
    if note is None:
        # Superseded by a newer tending run — its own callback will apply.
        return {"status": "stale"}

    if action_run.status != ActionRunStatus.SUCCEEDED:
        error = action_run.error_payload or {}
        note.tending_error = str(error.get("message") or error.get("error") or "Tending failed.")
        note.save(update_fields=["tending_error", "updated_at"])
        return {"status": "failed"}

    result = (action_run.result_payload or {}).get("result") or {}
    provenance = result.get("provenance") or {}
    try:
        confidence = float(result.get("shape_confidence"))
    except (TypeError, ValueError):
        confidence = None

    note.suggested_shape = coerce_shape(result.get("shape"))
    note.shape_confidence = confidence
    note.summary = (result.get("summary") or "").strip()
    from django.contrib.contenttypes.models import ContentType
    from storyboard.services import match_entity_alias

    previous = {
        (m.get("surface", "").casefold(), m.get("kind")): m
        for m in note.mentions if isinstance(m, dict) and m.get("confirmed_entity_id")
    }
    candidates = []
    for mention in result.get("mentions") or []:
        if not isinstance(mention, dict) or not mention.get("surface"):
            continue
        surface = str(mention["surface"]).strip()
        kind = "setting" if mention.get("kind") == "place" else mention.get("kind")
        if kind not in {"character", "setting", "thing", "concept"} or surface.casefold() not in note.text.casefold():
            continue
        try:
            mention_confidence = max(0.0, min(1.0, float(mention.get("confidence", 0))))
        except (TypeError, ValueError):
            mention_confidence = 0.0
        match = None
        if note.created_by_id:
            match = match_entity_alias(
                sponsor_content_type=ContentType.objects.get_for_model(note.created_by),
                sponsor_object_id=note.created_by_id,
                kind=kind,
                surface=surface,
            )
        candidate = {"surface": surface, "kind": kind, "confidence": mention_confidence,
                     "existing_entity_id": str(match.id) if match else None}
        prior = previous.get((surface.casefold(), kind))
        if prior:
            candidate["confirmed_entity_id"] = prior["confirmed_entity_id"]
            candidate["confirmed_kind"] = prior.get("confirmed_kind", kind)
        candidates.append(candidate)
    note.mentions = candidates
    note.tending_model = str(provenance.get("model") or "")[:128]
    note.tending_prompt_version = str(provenance.get("prompt_version") or "")[:64]
    note.tended_at = timezone.now()
    note.tending_error = ""
    note.save(update_fields=[
        "suggested_shape",
        "shape_confidence",
        "summary",
        "mentions",
        "tending_model",
        "tending_prompt_version",
        "tended_at",
        "tending_error",
        "updated_at",
    ])
    _notify(note, "folio_note:tended")
    return {"status": "ok", "shape": note.suggested_shape}
