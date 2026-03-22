# initiatives/tasks.py

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def run_artifact_quality_scan(self, artifact_id: str):
    """
    Async quality scan for Direct Annotations.

    Checks for fidelity (says something concrete) and cruft (too brief / vague).
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
        logger.info("quality_scan_complete artifact=%s assessment=%s", artifact_id, result.get("assessment"))

    except Exception as exc:
        logger.exception("quality_scan_failed artifact=%s", artifact_id)
        raise self.retry(exc=exc, countdown=60)


def _call_quality_scan(artifact) -> dict:
    """
    Call the Anthropic API to assess artifact quality.
    Returns {"assessment": "ok" | "advisory", "note": str}.

    Placeholder until AI integration is wired.
    """
    # TODO: Replace with InitiativeAIService.quality_scan() in AI integration pass
    body = (artifact.body or "").strip()
    if len(body) < 20:
        return {
            "assessment": "advisory",
            "note": "Body is very short. Consider adding more context before adding this to the timeline.",
        }
    return {"assessment": "ok", "note": ""}


@shared_task(bind=True, max_retries=3)
def update_rolling_summary(self, initiative_id: str, session_id: str):
    """
    Regenerate the Initiative's rolling summary after a session is committed.

    Combines prior rolling_summary with the newly committed distillation.
    Updates all four structured sections.
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
        logger.info("rolling_summary_updated initiative=%s after session=%s", initiative_id, session_id)

    except Exception as exc:
        logger.exception("rolling_summary_update_failed initiative=%s", initiative_id)
        raise self.retry(exc=exc, countdown=120)


def _call_summary_update(initiative, session) -> dict:
    """
    Call the Anthropic API to produce an updated rolling summary.
    Returns a dict matching the four-section schema.

    Placeholder until AI integration is wired.
    """
    # TODO: Replace with InitiativeAIService.update_rolling_summary() in AI integration pass
    prior = initiative.rolling_summary_display
    distillation = session.distillation or {}

    # Naive merge — real version will be AI-generated
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
