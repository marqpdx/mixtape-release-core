# initiatives/tasks.py

import logging
import os

from celery import shared_task
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handover task
# ---------------------------------------------------------------------------

HANDOVER_LOCK_TTL = 300  # 5 minutes — debounce window between consecutive runs


@shared_task(
    name="initiatives.tasks.handover_task",
    bind=True,
    max_retries=0,
    ignore_result=True,
)
def handover_task(self, log_id: str):
    """
    Lock-debounced task that generates an AI handover draft for an ApertureLog.

    Triggered by post_save on ApertureLogEntry (any non-handoff entry). Acquires a
    5-minute cache lock so rapid bursts don't cause redundant generation — the first
    call wins, subsequent calls within the window are no-ops. The lock expires and
    the next new entry triggers a fresh run.

    On Inkwell failure: logs the error and leaves the existing draft unchanged.
    On no entries since last handoff: exits silently (no-op, no lock acquired).
    """
    from django.core.cache import cache

    lock_key = f"handover_draft_lock:{log_id}"
    acquired = cache.add(lock_key, "1", HANDOVER_LOCK_TTL)
    if not acquired:
        return

    _generate_handover_draft(log_id)


def _generate_handover_draft(log_id: str) -> None:
    from django.utils import timezone
    from initiatives.models import ApertureLog, ApertureLogEntryKind

    try:
        aperture_log = ApertureLog.objects.select_related("initiative").get(id=log_id)
    except ApertureLog.DoesNotExist:
        logger.warning("handover_task: ApertureLog %s not found", log_id)
        return

    window_from = aperture_log.last_handoff_at or aperture_log.created_at
    window_to = timezone.now()

    entries = list(
        aperture_log.entries
        .filter(created_at__gt=window_from, deleted_at__isnull=True)
        .exclude(kind=ApertureLogEntryKind.HANDOFF)
        .order_by("created_at")
    )

    if not entries:
        logger.info("handover_task: no entries in window for log %s — skip", log_id)
        return

    corpus = [
        {
            "id": str(e.id),
            "kind": e.kind,
            "body": e.body,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]

    initiative = aperture_log.initiative
    try:
        from inkwell.client import InkwellUnavailableError, synthesize
        result = synthesize(
            corpus=corpus,
            synthesis_goal="Generate a handover note for this Initiative session window.",
            synthesis_mode="handover",
            group_context={
                "initiative_id": str(initiative.id),
                "initiative_title": initiative.title,
            },
        )
    except Exception as exc:
        logger.error(
            "handover_task: Inkwell call failed for log %s: %s",
            log_id, exc,
        )
        return

    draft = {
        "generated_at": window_to.isoformat(),
        "entry_window_from": window_from.isoformat(),
        "entry_window_to": window_to.isoformat(),
        "draft_body": result.get("synthesis", ""),
        "entry_count": len(entries),
        "model": result.get("model", "inkwell/synthesize"),
    }
    ApertureLog.objects.filter(pk=log_id).update(handover_draft=draft)
    logger.info(
        "handover_task: draft written log=%s entries=%d",
        log_id, len(entries),
    )


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def transcribe_initiatives_job(self, job_id: str):
    """
    Transcribe uploaded voice audio for an Initiatives mobile command.
    Updates AgentTranscriptionJob with the result and deletes the audio file.
    """
    from initiatives.models import AgentTranscriptionJob, AgentTranscriptionStatus
    from concord.services.whisper import transcribe_audio

    try:
        job = AgentTranscriptionJob.objects.get(id=job_id)
    except AgentTranscriptionJob.DoesNotExist:
        logger.warning("transcribe_initiatives_job: job %s not found", job_id)
        return

    if job.status != AgentTranscriptionStatus.PROCESSING:
        return

    audio_path = job.audio_path
    try:
        result = transcribe_audio(audio_path)
        job.transcription_text = result.text.strip()
        job.status = AgentTranscriptionStatus.COMPLETE
        job.save(update_fields=["transcription_text", "status", "updated_at"])
        logger.info("transcribe_initiatives_job: complete job=%s chars=%d", job_id, len(result.text))
    except Exception as exc:
        logger.exception("transcribe_initiatives_job: failed job=%s", job_id)
        job.status = AgentTranscriptionStatus.FAILED
        job.failure_reason = str(exc)[:500]
        job.save(update_fields=["status", "failure_reason", "updated_at"])
        raise self.retry(exc=exc)
    finally:
        try:
            if audio_path and default_storage.exists(audio_path):
                default_storage.delete(audio_path)
        except Exception:
            pass


@shared_task(bind=True, max_retries=3)
def run_artifact_quality_scan(self, artifact_id: str):
    """
    Async quality scan for Direct Annotations.

    Uses InitiativeAIService to assess fidelity and clarity.
    Sets artifact.quality_scan_result and quality_scan_state on completion.
    """
    from initiatives.models import Artifact, QualityScanState

    try:
        artifact = Artifact.objects.get(id=artifact_id)
    except Artifact.DoesNotExist:
        logger.warning("run_artifact_quality_scan: artifact %s not found", artifact_id)
        return

    if artifact.quality_scan_state == QualityScanState.COMPLETE:
        return  # Already scanned

    try:
        result = _call_quality_scan(artifact)
        artifact.quality_scan_result = result
        artifact.quality_scan_state = QualityScanState.COMPLETE
        artifact.save(update_fields=["quality_scan_result", "quality_scan_state", "updated_at"])
        logger.info(
            "quality_scan_complete artifact=%s assessment=%s",
            artifact_id,
            result.get("assessment"),
        )

    except Exception as exc:
        logger.exception("quality_scan_failed artifact=%s", artifact_id)
        raise self.retry(exc=exc, countdown=60)


def _call_quality_scan(artifact) -> dict:
    """
    Calls InitiativeAIService.quality_scan().
    Falls back to a length heuristic if AI is unavailable.
    Returns {"assessment": "ok" | "advisory", "note": str}.
    """
    try:
        from initiatives.ai.service import InitiativeAIService
        ai = InitiativeAIService()
        return ai.quality_scan(artifact)
    except Exception as exc:
        logger.warning("ai_quality_scan_unavailable artifact=%s error=%s", artifact.id, exc)
        # Heuristic fallback
        body = (artifact.body or "").strip()
        if len(body) < 20:
            return {
                "assessment": "advisory",
                "note": "Body is very short. Consider adding more context.",
            }
        return {"assessment": "ok", "note": ""}


@shared_task(bind=True, max_retries=3)
def update_rolling_summary(self, initiative_id: str, session_id: str):
    """
    Regenerate the Initiative's rolling summary after a session is committed.

    Uses InitiativeAIService to synthesise the prior summary with the
    newly committed distillation into a fresh structured summary.
    """
    from initiatives.models import Initiative, Session

    try:
        initiative = Initiative.objects.get(id=initiative_id)
        session = Session.objects.get(id=session_id)
    except (Initiative.DoesNotExist, Session.DoesNotExist) as exc:
        logger.warning("update_rolling_summary: object not found — %s", exc)
        return

    try:
        new_summary = _call_summary_update(initiative, session)
        from django.utils import timezone
        initiative.rolling_summary = new_summary
        initiative.rolling_summary_updated_at = timezone.now()
        initiative.rolling_summary_updated_by = "ai"
        initiative.save(update_fields=[
            "rolling_summary",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "updated_at",
        ])
        logger.info(
            "rolling_summary_updated initiative=%s after session=%s",
            initiative_id,
            session_id,
        )

    except Exception as exc:
        logger.exception("rolling_summary_update_failed initiative=%s", initiative_id)
        raise self.retry(exc=exc, countdown=120)


def _call_summary_update(initiative, session) -> dict:
    """
    Calls InitiativeAIService.update_rolling_summary().
    Falls back to a naive merge if AI is unavailable.
    """
    try:
        from initiatives.ai.service import InitiativeAIService
        ai = InitiativeAIService()
        return ai.update_rolling_summary(initiative, session)
    except Exception as exc:
        logger.warning(
            "ai_rolling_summary_unavailable initiative=%s error=%s",
            initiative.id,
            exc,
        )
        # Fallback: naive merge
        prior = initiative.rolling_summary_display
        distillation = session.distillation or {}

        decisions = list(prior.get("key_decisions", []))
        for d in distillation.get("decisions", []):
            if d and d not in decisions:
                decisions.append(d)

        questions = list(prior.get("open_questions", []))
        for q in distillation.get("open_questions", []):
            if q and q not in questions:
                questions.append(q)

        return {
            "current_direction": prior.get("current_direction", ""),
            "key_decisions": decisions,
            "open_questions": questions,
            "where_we_are_now": prior.get("where_we_are_now", ""),
        }
