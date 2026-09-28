# scrap/tasks.py
#
# Concrete CountNagKeeper instance (Keeper ADR AD-8, K-6): nags when an
# owner's raw (untriaged) Scrap pile crosses a threshold. The generic
# type contract lives in clio/count_nag.py; this file is the pile-specific
# half AD-8 leaves to the owning subsystem — the counting query and the
# answer_task Clio dispatches by name.

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

RAW_SCRAP_PILE_THRESHOLD = 20
RAW_SCRAP_NAG_MESSAGE = "You have {count} untriaged scraps — time to review your raw pile."


def _pile_keeper_id(content_type_id: int, owner_object_id) -> str:
    return f"count-nag-keeper.raw-scraps.{content_type_id}.{owner_object_id}"


def _raw_scrap_count(content_type_id: int, owner_object_id) -> int:
    from scrap.models import Scrap, ScrapStatus

    return Scrap.objects.filter(
        content_type_id=content_type_id,
        owner_object_id=owner_object_id,
        status=ScrapStatus.RAW,
        deleted_at__isnull=True,
    ).count()


def ensure_and_check_raw_scrap_pile(content_type_id: int, owner_object_id) -> None:
    """
    Called from scrap/signals.py on every raw Scrap creation. Registers
    this owner's CountNagKeeper instance if it doesn't already have an
    active one (idempotent), then checks the current count against the
    instance's threshold and submits a nag finding if crossed.
    """
    keeper_id = _pile_keeper_id(content_type_id, owner_object_id)
    try:
        from clio.count_nag import check_and_submit_nag, ensure_count_nag_keeper_registered

        ensure_count_nag_keeper_registered(
            keeper_id=keeper_id,
            keeper_name="CountNagKeeper — raw scrap pile",
            owner_subsystem="scrap",
            watch_scope=(
                f"scrap.Scrap rows with status='raw' for owner "
                f"(content_type={content_type_id}, object_id={owner_object_id})"
            ),
            intent="raw_scrap_pile_threshold",
            answer_task="scrap.tasks.answer_raw_scrap_pile_question",
            threshold=RAW_SCRAP_PILE_THRESHOLD,
            nag_message=RAW_SCRAP_NAG_MESSAGE,  # kept as a template; {count} filled in at surface time
        )
        count = _raw_scrap_count(content_type_id, owner_object_id)
        check_and_submit_nag(
            keeper_id=keeper_id,
            current_count=count,
            sponsor_content_type_id=content_type_id,
            sponsor_object_id=owner_object_id,
        )
    except Exception as exc:
        logger.warning("[count-nag-keeper] raw scrap pile check failed for %s: %s", keeper_id, exc)


@shared_task(queue="catalyst")
def answer_raw_scrap_pile_question(keeper_id: str, intent: str, question_params: dict) -> dict:
    """
    AD-11 answer_task for this instance's question shape
    ("raw_scrap_pile_threshold"). question_params must carry
    content_type_id and owner_object_id — Clio's routing has no notion of
    "which pile," so the caller supplies the same identity the instance
    was registered against.
    """
    from clio.count_nag import build_threshold_answer

    content_type_id = question_params.get("content_type_id")
    owner_object_id = question_params.get("owner_object_id")
    if not content_type_id or not owner_object_id:
        return {
            "intent": intent,
            "keeper_id": keeper_id,
            "answer": {"error": "content_type_id and owner_object_id are required"},
            "confidence": None,
        }

    count = _raw_scrap_count(content_type_id, owner_object_id)
    return build_threshold_answer(keeper_id=keeper_id, intent=intent, current_count=count)
