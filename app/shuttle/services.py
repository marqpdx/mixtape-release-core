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
# Building the packet itself from weave_in.text (recognizing places,
# things, Ideas and adjacencies) is not this module's job yet — that is
# Shuttle's agent work (SH-8), gated on OQ4/OQ6/OQ7. This module only
# implements the envelope: hold, validate, key to an ActionRun. Callers
# supply an already-built packet (today: a fixture or a hand-assembled
# dict; later: SH-8's agent).
from django.conf import settings

from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus

from .contract.validate import validate_packet_out, validate_weave_in

_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


class ShuttleEnvelopeError(Exception):
    pass


def hold_packet(*, weave_in: dict, packet: dict, author) -> dict:
    """
    Hold a built packet transiently, keyed to a new ActionRun (one per
    weave, OQ2b). Returns the packet with its action_run_id filled in —
    this is the dict served to the client as packet_out.

    `packet` is accepted pre-built (see module docstring); it must
    validate once action_run_id is attached. weave_in is validated and
    kept as part of the hold, for audit and for the eventual agent step
    that builds packets from it.
    """
    validate_weave_in(weave_in)

    action_run = ActionRun.objects.create(
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

    held_packet = {**packet, "version": "1.0", "action_run_id": str(action_run.id)}
    validate_packet_out(held_packet)

    action_run.request_payload = {**action_run.request_payload, "packet": held_packet}
    action_run.save(update_fields=["request_payload", "updated_at"])

    return held_packet


def get_held_packet(*, action_run_id: str) -> dict:
    """Fetch the packet held for a pending ActionRun. Raises ShuttleEnvelopeError
    if the ActionRun is unknown or has already moved past PENDING."""
    try:
        action_run = ActionRun.objects.get(pk=action_run_id)
    except ActionRun.DoesNotExist as exc:
        raise ShuttleEnvelopeError(f"No ActionRun held for {action_run_id}") from exc

    if action_run.status != ActionRunStatus.PENDING:
        raise ShuttleEnvelopeError(
            f"ActionRun {action_run_id} is not pending confirmation (status={action_run.status})"
        )

    packet = (action_run.request_payload or {}).get("packet")
    if packet is None:
        raise ShuttleEnvelopeError(f"ActionRun {action_run_id} has no held packet")
    return packet
