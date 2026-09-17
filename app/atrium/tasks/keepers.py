# atrium/tasks/keepers.py
#
# RecencyKeeper (Keeper ADR AD-7, K-5) — the first Keeper built from scratch
# against the K-1/K-2/K-3 framework (contrast Continuous Keeper, K-4, which
# wired up pre-existing Phase 2D code).
#
# Registration is a live, dotted-path match against AD-10's own worked
# example: keeper_id "recency-keeper", intent "recency_lookup", answer_task
# "atrium.tasks.keepers.answer_recency_question" — which is why this file
# exists as its own module rather than living in atrium/tasks/__init__.py.
#
# Watch mechanism: a live query over existing BaseModel.updated_at timestamps
# (auto_now=True on every model) for a narrow, explicit allow-list of
# owner-scoped content models — no new event-capture table. v1 scope:
# writing.Seed (quick captures) and writing.WorkingDocument (in-progress
# writing pieces), both already indexed on (author/user, updated_at).
# Expand the allow-list in _RECENCY_SOURCES to widen scope later.

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


def _ensure_recency_keeper_registered() -> None:
    """
    Idempotent registration against Clio's registry (AD-10's own worked
    example payload). Safe to call repeatedly — ensure_keeper_registered
    returns the existing active registration rather than treating every
    call as a restart (AD-5's restart semantics apply to an actual respawn,
    not to a heartbeat re-confirming a still-running singleton).
    """
    try:
        from clio import services as clio_services

        clio_services.ensure_keeper_registered(
            keeper_id="recency-keeper",
            keeper_name="RecencyKeeper",
            owner_subsystem="atrium",
            watch_scope=(
                "writing.Seed and writing.WorkingDocument rows, scoped by owner, "
                "via existing updated_at timestamps (no dedicated event capture)."
            ),
            question_shapes=[
                {
                    "intent": "recency_lookup",
                    "description": "What was most recently worked on?",
                    "answer_task": "atrium.tasks.keepers.answer_recency_question",
                }
            ],
            finding_cadence="reactive",
            closing_mode="archive",
            instance_params={},
        )
    except Exception as exc:
        logger.warning("[recency-keeper] registration failed: %s", exc)


@shared_task(queue="catalyst")
def register_recency_keeper_task() -> None:
    """
    Celery beat heartbeat (see mixtape/celery_app.py beat_schedule) that
    keeps RecencyKeeper's registration alive. RecencyKeeper is long-lived
    system infrastructure, not spawned per-request like Continuous Keeper,
    so it needs a registration bootstrap independent of any particular
    question being asked — Clio's routing only ever reaches an already-
    registered Keeper (see AD-11), so self-registering lazily inside
    answer_recency_question would be too late for the very first question.
    """
    _ensure_recency_keeper_registered()


@shared_task(queue="catalyst")
def answer_recency_question(keeper_id: str, intent: str, question_params: dict) -> dict:
    """
    AD-11 answer_task. Signature and standardized answer shape are fixed by
    the ADR: (keeper_id, intent, question_params) -> {intent, keeper_id,
    answer, confidence}.

    question_params:
      owner_id (required) — pk of the member whose recent objects to list.
      limit (optional, default 10, max 50).
    """
    owner_id = question_params.get("owner_id")
    if not owner_id:
        return {
            "intent": intent,
            "keeper_id": keeper_id,
            "answer": {"error": "owner_id is required", "recent_objects": []},
            "confidence": None,
        }

    limit = question_params.get("limit") or _DEFAULT_LIMIT
    try:
        limit = min(int(limit), _MAX_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    from writing.models import Seed, WorkingDocument

    recent_objects = []

    seeds = (
        Seed.objects.filter(author_id=owner_id, deleted_at__isnull=True)
        .order_by("-updated_at")[:limit]
    )
    for seed in seeds:
        recent_objects.append({
            "object_type": "seed",
            "id": str(seed.id),
            "title": (seed.body_text or "")[:80].strip(),
            "updated_at": seed.updated_at.isoformat(),
        })

    documents = (
        WorkingDocument.objects.filter(user_id=owner_id, deleted_at__isnull=True)
        .select_related("piece")
        .order_by("-updated_at")[:limit]
    )
    for doc in documents:
        recent_objects.append({
            "object_type": "working_document",
            "id": str(doc.id),
            "title": doc.title or getattr(doc.piece, "title", "") or "",
            "updated_at": doc.updated_at.isoformat(),
        })

    recent_objects.sort(key=lambda obj: obj["updated_at"], reverse=True)
    recent_objects = recent_objects[:limit]

    return {
        "intent": intent,
        "keeper_id": keeper_id,
        "answer": {"recent_objects": recent_objects},
        "confidence": None,
    }
