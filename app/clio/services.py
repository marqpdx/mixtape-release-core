"""
clio/services.py — plain Python entry points into the Keeper registry, for
same-process callers (other Django apps in this monolith). Mirrors this
codebase's producer-import convention (e.g. activity.producers) rather than
having an in-process caller round-trip through its own HTTP API with a
self-minted service token — that machinery exists for genuinely external
callers (Switchboard, Inkwell), not app-to-app calls within one process.

clio/api/views.py wraps these same functions for external HTTP callers;
keep behavior in sync between the two — the views should stay thin.
"""

import logging

from django.utils import timezone

from clio.models import (
    KeeperClosingMode,
    KeeperFinding,
    KeeperRegistration,
    KeeperRegistrationStatus,
)

logger = logging.getLogger(__name__)


def close_registration(registration: KeeperRegistration, *, closing_mode: str) -> None:
    """
    Apply AD-5's drop/archive semantics. Drop is a real delete; archive
    retains the full row (payload, owner, timestamp) and is never deleted.
    """
    if closing_mode == KeeperClosingMode.DROP:
        registration.delete()
        return
    registration.status = KeeperRegistrationStatus.ARCHIVED
    registration.archived_at = timezone.now()
    registration.save(update_fields=["status", "archived_at", "updated_at"])


def register_keeper(
    *,
    keeper_id: str,
    keeper_name: str,
    owner_subsystem: str,
    watch_scope: str,
    finding_cadence: str,
    question_shapes: list | None = None,
    closing_mode: str = KeeperClosingMode.ARCHIVE,
    instance_params: dict | None = None,
) -> KeeperRegistration:
    """
    AD-10 registration. A restarted Keeper is always a new registration
    (AD-5) — if an active registration already exists under the same
    keeper_id, it is implicitly closed (using its own declared closing mode)
    before the new one is created, rather than raising a conflict.
    """
    existing = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).first()
    if existing:
        logger.info(
            "Keeper '%s' re-registered while an active registration existed; closing prior registration (mode=%s).",
            keeper_id,
            existing.closing_mode,
        )
        close_registration(existing, closing_mode=existing.closing_mode)

    question_shapes = question_shapes or []
    return KeeperRegistration.objects.create(
        keeper_id=keeper_id,
        keeper_name=keeper_name,
        owner_subsystem=owner_subsystem,
        watch_scope=watch_scope,
        question_shapes=question_shapes,
        intents=[shape["intent"] for shape in question_shapes],
        finding_cadence=finding_cadence,
        closing_mode=closing_mode or KeeperClosingMode.ARCHIVE,
        instance_params=instance_params or {},
    )


def ensure_keeper_registered(
    *,
    keeper_id: str,
    keeper_name: str,
    owner_subsystem: str,
    watch_scope: str,
    finding_cadence: str,
    question_shapes: list | None = None,
    closing_mode: str = KeeperClosingMode.ARCHIVE,
    instance_params: dict | None = None,
) -> KeeperRegistration:
    """
    Idempotent variant of register_keeper: returns the existing active
    registration if one already exists for this keeper_id, rather than
    treating every call as a restart (AD-5's restart semantics apply to an
    actual respawn, not to "this Keeper is still continuously operating").
    Use this from a trigger/loop call site invoked many times over a
    Keeper's ongoing lifetime; use register_keeper directly only at an
    actual spawn/restart boundary.
    """
    existing = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).first()
    if existing:
        return existing
    return register_keeper(
        keeper_id=keeper_id,
        keeper_name=keeper_name,
        owner_subsystem=owner_subsystem,
        watch_scope=watch_scope,
        finding_cadence=finding_cadence,
        question_shapes=question_shapes,
        closing_mode=closing_mode,
        instance_params=instance_params,
    )


def deregister_keeper(*, keeper_id: str, closing_mode: str | None = None) -> KeeperRegistration | None:
    """
    AD-5 deregistration. closing_mode overrides the registration's own
    declared preference for this deregistration only; omit to use what was
    declared at registration time. Returns None if no active registration
    exists for keeper_id (a no-op, not an error — mirrors AD-11's
    no_keeper_available stance that absence is a valid state).
    """
    registration = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).first()
    if registration is None:
        return None
    effective_closing_mode = closing_mode or registration.closing_mode
    close_registration(registration, closing_mode=effective_closing_mode)
    return registration


def submit_finding(
    *,
    keeper_id: str,
    finding_type: str,
    suggested_clio_signal: str,
    finding_body: dict | None = None,
) -> KeeperFinding:
    """
    AD-12 proactive finding submission — store-and-defer scope (K-3).
    Raises ValueError if keeper_id has no active registration; unregistered
    Keepers cannot submit findings. Does not surface the finding anywhere —
    see KeeperFinding's docstring for why (ClioState integration is a
    separate, deliberately deferred follow-up).
    """
    is_registered = KeeperRegistration.objects.filter(
        keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
    ).exists()
    if not is_registered:
        raise ValueError(f"'{keeper_id}' has no active registration. Unregistered Keepers cannot submit findings.")

    return KeeperFinding.objects.create(
        keeper_id=keeper_id,
        finding_type=finding_type,
        finding_body=finding_body or {},
        suggested_clio_signal=suggested_clio_signal,
    )
