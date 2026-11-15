"""Local model boundary on the existing ordered lifecycle and child store.

Dispatch records one real child/request. Only the surface's atomic claim may
start it; broker text is never authority to call a host.
"""
from uuid import uuid4

from django.conf import settings
from django.db import transaction

from initiatives.models import ActionRun
from . import steps
from .bundle import digest
from .errors import InterpretationError


def enabled(reading):
    if not reading.local_enabled_setting or not getattr(settings, reading.local_enabled_setting, False):
        raise InterpretationError("backend_unavailable", 503)


def dispatch(parent, state, reading, step, author):
    from .lifecycle import _enqueue
    from .ordered import binding
    enabled(reading)
    steps.assert_current(reading, state, author, parent)
    record = next(r for r in state["steps"] if r["id"] == step.id)
    execution_id = uuid4()
    bound = binding(reading, state, record)
    payload = step.build_request(steps.inputs(state), {**bound,
        "weave_action_run_id": str(parent.pk), "execution_action_run_id": str(execution_id)})
    fingerprint = digest(payload)
    child = ActionRun.objects.create(id=execution_id, parent_action=parent,
        tool_name=f"capability.{reading.capability}", service_name="switchboard",
        status="pending", execution_mode="local", cloud_approved=False,
        tenant_id=parent.tenant_id, tenant_namespace=parent.tenant_namespace,
        initiator_type="human", initiator_id=str(author.pk),
        request_payload={**bound, "capability_payload": payload, "request_fingerprint": fingerprint,
                         "cloud_requested": False, "local_only": True})
    record.update(status="running", execution_action_run_id=str(child.pk))
    state.update(execution_id=str(child.pk), status="pending")
    # No source text or caller-controlled callback is sent through the broker.
    reference = {"execution_action_run_id": str(child.pk), "request_fingerprint": fingerprint}
    kwargs = {"action_run_id": str(child.pk), "tenant_id": str(parent.tenant_id),
        "tenant_namespace": parent.tenant_namespace, "principal_user_id": str(author.pk),
        "principal_service_token_id": None, "capability": reading.capability,
        "capability_payload": reference, "cloud_mode": False, "escalation_approved": False}

    def enqueue():
        _enqueue(str(child.pk), kwargs)
        if ActionRun.objects.filter(pk=child.pk, status="failed").exists():
            from .tasks import apply_interpretation
            apply_interpretation(str(child.pk), reading=reading)

    transaction.on_commit(enqueue)


def assert_cloud_allowed(parent, author):
    refs = (parent.request_payload or {}).get("folio_source")
    if refs:
        from folio.services.interpretation import owned_folio
        from folio.models import FolioNote
        folio = owned_folio(author, refs["folio_id"])
        if not FolioNote.objects.filter(pk=refs["note_id"], folio=folio, deleted_at__isnull=True).exists():
            raise InterpretationError("note_moved_or_unavailable", 409)
        if folio.local_only:
            raise InterpretationError("policy_forbids_cloud", 403)
