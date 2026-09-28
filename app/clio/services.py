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
    sponsor_content_type_id: int | None = None,
    sponsor_object_id=None,
) -> KeeperFinding:
    """
    AD-12 proactive finding submission. As of CLIO-1b (2026-09-28), findings
    with a resolvable sponsor now surface through ClioState's signal-salience
    model (see studio/views.py's _build_clio_prompt and
    get_keeper_signal_for_profile below). sponsor_content_type_id/
    sponsor_object_id are optional — a Keeper that cannot resolve an owner
    (or a caller not yet updated) submits with sponsor=None, which stores
    and defers exactly as before K-3 always did.

    Raises ValueError if keeper_id has no active registration; unregistered
    Keepers cannot submit findings.
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
        sponsor_content_type_id=sponsor_content_type_id,
        sponsor_object_id=sponsor_object_id,
    )


def get_keeper_signal_for_profile(profile, *, signals: list[str], after=None) -> KeeperFinding | None:
    """
    CLIO-1b: the oldest unsurfaced KeeperFinding sponsored by `profile`
    personally, by any Group they're an active member of, or by the
    platform default group (settings.MIXTAPE_DEFAULT_GROUP_SLUG — a
    genuinely site-wide finding), matching one of `signals`
    (suggested_clio_signal values).

    `after` mirrors ClioState.last_surfaced_at: only findings submitted
    after this cutoff are eligible — the same convention Signal 1
    (ApertureLog) already uses in studio/views.py. There is no separate
    "surfaced" flag on KeeperFinding by design (see its docstring).
    """
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Q

    from groups.models import Group, GroupMembership

    User = get_user_model()
    profile_ct = ContentType.objects.get_for_model(type(profile))
    group_ct = ContentType.objects.get_for_model(Group)
    user_ct = ContentType.objects.get_for_model(User)

    group_ids = list(
        GroupMembership.objects.filter(
            member_content_type=user_ct,
            member_object_id=profile.user_id,
            is_active=True,
        ).values_list("group_id", flat=True)
    )

    default_slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "crossroads")
    default_group_id = Group.objects.filter(slug=default_slug).values_list("pk", flat=True).first()
    if default_group_id and default_group_id not in group_ids:
        group_ids.append(default_group_id)

    qs = KeeperFinding.objects.filter(
        Q(sponsor_content_type=profile_ct, sponsor_object_id=profile.pk)
        | Q(sponsor_content_type=group_ct, sponsor_object_id__in=group_ids)
    ).filter(suggested_clio_signal__in=signals)

    if after:
        qs = qs.filter(submitted_at__gt=after)

    return qs.order_by("submitted_at").first()
