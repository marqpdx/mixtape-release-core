# clio/count_nag.py
#
# Shared instantiation helper for CountNagKeeper (Keeper ADR AD-8, K-6).
#
# CountNagKeeper is not a bespoke watcher per pile (AD-8): it is a single
# Keeper *type*, instantiated per pile with pile-specific parameters
# (threshold, nag message, target Clio signal). This module is the shared
# "type" contract every instance is built against — registration shape,
# the threshold-check, and finding submission are common. Each subsystem
# still owns its own pile-specific counting query and its own answer_task
# dotted path (AD-10 requires a concrete answer_task per question shape;
# there is no way to make "count this owner's rows" generic across
# arbitrary querysets without real over-engineering for a first instance
# — see scrap/tasks.py for the concrete example).

import logging

logger = logging.getLogger(__name__)


def ensure_count_nag_keeper_registered(
    *,
    keeper_id: str,
    keeper_name: str,
    owner_subsystem: str,
    watch_scope: str,
    intent: str,
    answer_task: str,
    threshold: int,
    nag_message: str,
    clio_signal: str = "nag",
) -> None:
    """
    Idempotent registration (AD-10). instance_params carries the
    pile-specific parameters AD-8 names: threshold, nag message, and
    target Clio signal — opaque to Clio, relayed to the Keeper unchanged.

    finding_cadence is "both": every instance declares a question shape
    ("has this pile crossed its threshold?") AND proactively nags when
    crossed (AD-8: "the nag is the finding"). closing_mode is "drop" —
    keeper-library.md: drop when the pile no longer needs watching.
    """
    try:
        from clio import services as clio_services

        clio_services.ensure_keeper_registered(
            keeper_id=keeper_id,
            keeper_name=keeper_name,
            owner_subsystem=owner_subsystem,
            watch_scope=watch_scope,
            question_shapes=[
                {
                    "intent": intent,
                    "description": "Has this pile crossed its threshold?",
                    "answer_task": answer_task,
                }
            ],
            finding_cadence="both",
            closing_mode="drop",
            instance_params={
                "threshold": threshold,
                "nag_message": nag_message,
                "clio_signal": clio_signal,
            },
        )
    except Exception as exc:
        logger.warning("[count-nag-keeper] registration failed for %s: %s", keeper_id, exc)


def build_threshold_answer(*, keeper_id: str, intent: str, current_count: int) -> dict:
    """
    AD-11 standardized answer shape for the "has this pile crossed its
    threshold?" question shape every CountNagKeeper instance declares.
    Reads the threshold from the instance's own registration rather than
    requiring the caller to pass it — instance_params is the single
    source of truth for a given keeper_id.
    """
    from clio.models import KeeperRegistration, KeeperRegistrationStatus

    reg = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).first()
    threshold = (reg.instance_params or {}).get("threshold") if reg else None
    crossed = threshold is not None and current_count >= threshold
    return {
        "intent": intent,
        "keeper_id": keeper_id,
        "answer": {"crossed": crossed, "current_count": current_count, "threshold": threshold},
        "confidence": None,
    }


def check_and_submit_nag(
    *,
    keeper_id: str,
    current_count: int,
    sponsor_content_type_id: int | None = None,
    sponsor_object_id=None,
) -> None:
    """
    AD-8's proactive half: if current_count has reached the instance's
    registered threshold, submit a K-3 finding.

    sponsor_content_type_id/sponsor_object_id (CLIO-1b, 2026-09-28) identify
    who this nag is for — pass through the same owner (content_type_id,
    owner_object_id) the caller already counts rows for, so the finding
    reaches that owner's ClioState feed. Optional: omitted, the finding
    still stores (store-and-defer) but never surfaces.

    No dedup against repeat crossings — matches K-4's Continuous Keeper
    precedent, which also submits one finding per qualifying event with
    no suppression. A resolved/unresolved model for findings is out of
    scope for this pass.
    """
    from clio.models import KeeperRegistration, KeeperRegistrationStatus

    reg = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).first()
    if reg is None:
        return
    params = reg.instance_params or {}
    threshold = params.get("threshold")
    if threshold is None or current_count < threshold:
        return

    try:
        from clio import services as clio_services

        nag_message = params.get("nag_message", "")
        try:
            rendered_message = nag_message.format(count=current_count)
        except (KeyError, IndexError):
            rendered_message = nag_message

        clio_services.submit_finding(
            keeper_id=keeper_id,
            finding_type="count_threshold_crossed",
            finding_body={
                "current_count": current_count,
                "threshold": threshold,
                "nag_message": nag_message,
                "message": rendered_message,
            },
            suggested_clio_signal=params.get("clio_signal", "nag"),
            sponsor_content_type_id=sponsor_content_type_id,
            sponsor_object_id=sponsor_object_id,
        )
    except Exception as exc:
        logger.warning("[count-nag-keeper] finding submission failed for %s: %s", keeper_id, exc)
