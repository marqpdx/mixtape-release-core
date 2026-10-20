# shuttle/services.py
#
# The Governed Verb Envelope's plan/preview half (ADR-0058 D2, SH-7b).
# Holds a packet transiently, keyed to one ActionRun per weave (OQ2) —
# the ActionRun's request_payload is the hold, not a separate queryable
# model like GristMill's MillDraft. The confirm half (which writes the
# real rows in one transaction) is a separate module, shuttle/confirm.py,
# landed in its own commit (CTO, 2026-10-19 — split plan/preview from
# confirm).
#
# start_weave and hold_packet are deliberately two functions, not one
# (Puddlejump review of ea96aee6, CTO, 2026-10-19 — decision 1 of the
# Shuttle ADR's 2026-10-19 Headnote): the envelope's ActionRun is created
# when interpretation first starts, before any packet exists, and the
# SH-11 mobile interpretation path hangs its own per-call runs under it
# via parent_action. start_weave is the one shared function that creates
# that ActionRun; hold_packet only attaches a packet to an existing one.
# A single hold_packet that always created its own ActionRun would give
# the same weave two runs once the interpretation path called in too.
#
# Building the packet itself from weave_in.text (recognizing places,
# things, Ideas and adjacencies) is not this module's job yet — that is
# Shuttle's agent work (SH-8), gated on OQ6/OQ7 (OQ4 resolved 2026-10-19).
# This module only implements the envelope: hold, validate, key to an
# ActionRun. Callers supply an already-built packet (today: a fixture or
# a hand-assembled dict; later: SH-8's agent).
from django.conf import settings
from django.utils import timezone

from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus

from .contract.validate import validate_packet_out, validate_weave_in

_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


class ShuttleEnvelopeError(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def start_weave(*, weave_in: dict, author) -> ActionRun:
    """
    Create the weave's envelope ActionRun (one per weave, OQ2b), before
    any packet exists. This is the shared function the SH-11 mobile
    interpretation path calls into as well, so a weave never ends up
    with two envelope runs — its own per-call interpretation records
    hang off this same ActionRun via parent_action.

    The envelope's tenant_id/tenant_namespace stay the platform default:
    the Commons is platform-wide, and the person-as-tenant decision
    (ADR Headnote, decision 2) applies to resolving the Claude runtime,
    not to this field.
    """
    validate_weave_in(weave_in)

    return ActionRun.objects.create(
        tool_name="shuttle.weave",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        service_name="shuttle",
        tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)),
        tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE)),
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(author.pk),
        request_payload={"weave_in": weave_in},
    )


def hold_packet(*, action_run_id: str, packet: dict, author) -> dict:
    """
    Attach a built packet to the weave's existing envelope ActionRun
    (started with start_weave). Returns the packet with its
    action_run_id filled in — this is the dict served to the client as
    packet_out.

    `author` must be the ActionRun's own initiator (required_authority
    "self" in the orchestration registry: the envelope's initiator,
    acting on their own weave) — a packet cannot be held against
    someone else's weave.
    """
    action_run = _get_pending_action_run_for(action_run_id=action_run_id, author=author)

    held_packet = {**packet, "version": "1.0", "action_run_id": str(action_run.id)}
    validate_packet_out(held_packet)

    action_run.request_payload = {**action_run.request_payload, "packet": held_packet}
    action_run.save(update_fields=["request_payload", "updated_at"])

    return held_packet


def abandon_weave(*, action_run_id: str, author) -> ActionRun:
    """
    Shuttle's explicit "Keep in Notebook" exit (ADR-0058, CTO 2026-10-20
    whole-weave amendment; OQ10). The person is stepping away without
    publishing — the envelope ActionRun moves to ABANDONED rather than
    being left PENDING forever (an invisible backlog D9 warns against).

    Nothing is deleted: the original Seed, interpretation findings,
    corrections and any held packet all stay exactly as they are, on the
    same ActionRun, for audit/inspection. Re-engaging is a fresh
    start_weave call (CTO, 2026-10-20 — "start fresh," not a resume of
    this run's revision chain); this function does not support resuming.
    """
    action_run = _get_pending_action_run_for(action_run_id=action_run_id, author=author)
    action_run.status = ActionRunStatus.ABANDONED
    action_run.completed_at = timezone.now()
    action_run.save(update_fields=["status", "completed_at", "updated_at"])
    return action_run


def get_held_packet(*, action_run_id: str, author) -> dict:
    """Fetch the packet held for a pending ActionRun, only for its own
    initiator (see hold_packet's authority note)."""
    action_run = _get_pending_action_run_for(action_run_id=action_run_id, author=author)

    packet = (action_run.request_payload or {}).get("packet")
    if packet is None:
        raise ShuttleEnvelopeError(f"ActionRun {action_run_id} has no held packet")
    return packet


def _get_pending_action_run_for(*, action_run_id: str, author) -> ActionRun:
    try:
        action_run = ActionRun.objects.get(pk=action_run_id)
    except ActionRun.DoesNotExist as exc:
        raise ShuttleEnvelopeError(f"No ActionRun held for {action_run_id}", status=404) from exc

    # Ownership mismatch reads as "not found," not 403 — don't reveal that an
    # action_run_id exists for someone else's weave.
    if action_run.initiator_id != str(author.pk):
        raise ShuttleEnvelopeError(
            f"ActionRun {action_run_id} does not belong to this requester.", status=404
        )

    if action_run.status != ActionRunStatus.PENDING:
        raise ShuttleEnvelopeError(
            f"ActionRun {action_run_id} is not pending confirmation (status={action_run.status})",
            status=409,
        )

    return action_run
