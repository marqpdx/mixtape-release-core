"""Opt-in ordered readings on the shared lifecycle, worker and ActionRun store."""
from __future__ import annotations

import copy
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from jsonschema import ValidationError

from initiatives.models import ActionRun, ActionRunStatus, ActionRunExecutionMode, ActionRunInitiatorType

from . import steps
from .bundle import digest, schema_validator
from .errors import InterpretationError


def save(parent, state):
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])


def binding(reading, state, record):
    return {**steps.identity(state), **steps.plan_identity(reading),
            "attempt_id": state["attempt_id"], "step_id": record["id"],
            "step_version": record["version"], "input_digest": record["input_digest"]}


def dispatch(parent, state, reading, step, author):
    from .lifecycle import _enqueue, person_runtime
    cloud = bool(getattr(settings, reading.cloud_setting_name, True))
    # There is no approved local execution adapter for these new steps yet.
    if not cloud:
        raise InterpretationError("backend_unavailable", 409)
    steps.assert_current(reading, state, author, parent)
    if not author.has_perm("initiatives.approve_cloud_dispatch"):
        raise InterpretationError("cloud_approval_not_permitted", 403)
    person_runtime(author, reading=reading)
    record = next(r for r in state["steps"] if r["id"] == step.id)
    data = steps.inputs(state)
    prompt = step.build_prompt(data)
    if not isinstance(prompt, str) or not prompt:
        raise InterpretationError("invalid_prompt")
    if len(prompt) > reading.max_prompt_chars:
        raise InterpretationError("prompt_too_long", 413)
    execution_id = uuid4()
    bound = binding(reading, state, record)
    payload = {"sources": state["sources"], "context": state["context"],
        **bound, "prompt": prompt, "response_schema": step.response_schema,
        "source_ref": f"{reading.tool_name}:{parent.pk}"}
    fingerprint = digest(payload)
    approval = {**bound, "request_fingerprint": fingerprint,
        "author_id": str(author.pk), "weave_action_run_id": str(parent.pk),
        "execution_action_run_id": str(execution_id), "capability": reading.capability,
        "approved_at": state["consent"]["approved_at"], "steps": state["consent"]["steps"]}
    child = ActionRun.objects.create(id=execution_id, tool_name=f"capability.{reading.capability}",
        parent_action=parent, service_name="switchboard", status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD,
        tenant_id=parent.tenant_id, tenant_namespace=parent.tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN, initiator_id=str(author.pk),
        cloud_approved=True, approval_payload=approval,
        request_payload={"capability_payload": payload, **bound, "request_fingerprint": fingerprint,
            "prompt_version": reading.prompt_version, "cloud_requested": True})
    record.update(status="running", execution_action_run_id=str(child.pk))
    state.update(execution_id=str(child.pk), status="pending")
    kwargs = {"action_run_id": str(child.pk), "tenant_id": str(parent.tenant_id),
        "tenant_namespace": parent.tenant_namespace, "principal_user_id": str(author.pk),
        "principal_service_token_id": None, "capability": reading.capability,
        "capability_payload": payload, "cloud_mode": True, "escalation_approved": True,
        "callback_task": reading.callback_task, "callback_queue": reading.callback_queue}
    def enqueue():
        _enqueue(str(child.pk), kwargs)
        if ActionRun.objects.filter(pk=child.pk, status=ActionRunStatus.FAILED).exists():
            from .tasks import apply_interpretation
            apply_interpretation(str(child.pk), reading=reading)
    transaction.on_commit(enqueue)


@transaction.atomic
def execute(*, author, action_run_id, request_id, expected_revision, digest_value,
            expected_context_revision, context_digest, reading, consent):
    from .lifecycle import owned_parent, snapshot, person_runtime
    parent = owned_parent(action_run_id, author, tool_name=reading.tool_name, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    steps.assert_current(reading, state, author, parent)
    expected = {"revision": expected_revision, "source_digest": digest_value,
                "context_revision": expected_context_revision, "context_digest": context_digest}
    if steps.identity(state) != expected:
        raise InterpretationError("revision_conflict", 409)
    key = f"execution:{request_id}"
    fingerprint = digest({**expected, **steps.plan_identity(reading)})
    if key in state["requests"]:
        if state["requests"][key]["fingerprint"] != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return snapshot(parent, reading=reading)
    if state.get("execution_id") and parent.child_actions.filter(pk=state["execution_id"],
            status__in=[ActionRunStatus.PENDING, ActionRunStatus.RUNNING]).exists():
        raise InterpretationError("execution_in_progress", 409)
    if any(s.kind == "model" for s in reading.steps):
        if not consent:
            raise InterpretationError("cloud_approval_required", 403)
        if not getattr(settings, reading.cloud_setting_name, True):
            raise InterpretationError("backend_unavailable", 409)
        if not author.has_perm("initiatives.approve_cloud_dispatch"):
            raise InterpretationError("cloud_approval_not_permitted", 403)
        person_runtime(author, reading=reading)
    steps.initialize(reading, state, request_id)
    state["consent"] = {"approved_at": timezone.now().isoformat(),
                        "steps": steps.definitions(reading), **expected}
    next_step = steps.advance(reading, state)
    if next_step:
        dispatch(parent, state, reading, next_step, author)
    state["requests"][key] = {"fingerprint": fingerprint, "attempt_id": str(request_id)}
    save(parent, state)
    return snapshot(parent, reading=reading)


@transaction.atomic
def refresh_context(*, author, action_run_id, expected_context_revision, reading):
    """Surface commits its orientation separately, then explicitly refreshes here.

    No cloud dispatch. The provider reads authoritative surface context.
    """
    from .lifecycle import owned_parent, snapshot
    parent = owned_parent(action_run_id, author, tool_name=reading.tool_name, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    if state["context"]["revision"] != expected_context_revision:
        raise InterpretationError("context_conflict", 409)
    current = steps.context_snapshot(reading, author, parent)
    if digest(current) == digest(state["context"]):
        return snapshot(parent, reading=reading)
    if current["revision"] <= expected_context_revision:
        raise InterpretationError("context_revision_required", 409)
    steps.archive(state)
    state.update(context=current, plan=steps.plan_identity(reading), findings=None,
                 execution_id=None, error=None, status="awaiting_cloud_approval")
    save(parent, state)
    return snapshot(parent, reading=reading)


def verify_worker(reading, parent, state, child, data, author):
    steps.assert_current(reading, state, author, parent)
    record = next((r for r in state["steps"] if r["execution_action_run_id"] == str(child.pk)), None)
    if record is None or record["status"] != "running":
        raise InterpretationError("superseded", 409)
    expected = binding(reading, state, record)
    approval = child.approval_payload or {}
    if (any(data.get(k) != v or approval.get(k) != v for k, v in expected.items()) or
            digest(data) != approval.get("request_fingerprint") or
            digest(data) != child.request_payload.get("request_fingerprint") or
            approval.get("steps") != steps.definitions(reading)):
        raise InterpretationError("cloud_approval_required", 403)


def validate_model_output(reading, child, output):
    data = child.request_payload["capability_payload"]
    step = next(s for s in reading.steps if s.id == data["step_id"])
    schema_validator(step.response_schema).validate(output)
    if step.validate:
        step.validate(output)


def apply(child, parent, state, reading, author):
    """Called under the shared apply worker's parent lock."""
    try:
        steps.assert_current(reading, state, author, parent)
        record = next(r for r in state["steps"] if r["execution_action_run_id"] == str(child.pk))
        if any(child.request_payload.get(k) != v for k, v in binding(reading, state, record).items()):
            return
    except InterpretationError:
        state.update(status="superseded", error=None, findings=None)
        save(parent, state)
        return  # Child keeps its actual outcome; stale results never replace current output.
    except StopIteration:
        return
    if record["status"] != "running":
        return
    if child.status == ActionRunStatus.FAILED:
        steps.failed(state, record, (child.error_payload or {}).get("error", "execution_failed"))
    elif child.status == ActionRunStatus.SUCCEEDED:
        try:
            result = child.result_payload["result"]
            output = result["findings"]
            validate_model_output(reading, child, output)
            step = next(s for s in reading.steps if s.id == record["id"])
            steps.accept_output(step, record, output)
            record["provenance"] = result["provenance"]
            state["execution_id"] = None
            next_step = steps.advance(reading, state)
            if next_step:
                dispatch(parent, state, reading, next_step, author)
        except (KeyError, TypeError, ValueError, ValidationError, InterpretationError):
            steps.failed(state, record, "invalid_output")
    else:
        return
    save(parent, state)
