# initiatives/tasks.py

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


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
