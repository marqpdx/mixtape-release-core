"""Generic bodies for the two-task completion pattern (run, then apply).
Each surface keeps its own @shared_task-decorated entry points (its own
task name and queue are part of its existing Switchboard wiring, and
`shuttle.interpretation.tasks` keeps its own module path for its tests'
mock targets) and calls straight through to these bodies with its own
Reading."""
from __future__ import annotations

import copy
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from jsonschema import ValidationError

from initiatives.models import ActionRun, ActionRunStatus

from .contract import Reading, source_digest
from .errors import InterpretationError
from .lifecycle import person_runtime


def fail(child_id, code, *, apply_fn):
    ActionRun.objects.filter(pk=child_id).update(status=ActionRunStatus.FAILED,
        error_payload={"error": code}, completed_at=timezone.now())
    apply_fn(str(child_id))


def run_cloud_interpretation(*, action_run_id, reading: Reading, apply_fn):
    # The Switchboard → Core worker pattern is shared with LinkedIn copy.
    # Core trusts no caller-provided source/principal/runtime; all are read from the recorded run.
    with transaction.atomic():
        child = ActionRun.objects.select_for_update().filter(pk=action_run_id,
            tool_name=f"capability.{reading.capability}").first()
        if child is None or child.status != ActionRunStatus.RUNNING:
            return
        payload = copy.deepcopy(child.request_payload or {})
        if payload.get("claimed"):
            return
        payload["claimed"] = True
        child.request_payload = payload
        child.save(update_fields=["request_payload", "updated_at"])
    try:
        parent = child.parent_action
        data = payload["capability_payload"]
        digest = source_digest(data["sources"])
        gate = (child.result_payload or {}).get("dispatch", {})
        approval = child.approval_payload or {}
        if (parent is None or parent.tool_name != reading.tool_name or
            parent.initiator_id != child.initiator_id or str(parent.tenant_id) != str(child.tenant_id)):
            raise InterpretationError("invalid_execution")
        if parent.status != ActionRunStatus.PENDING:
            raise InterpretationError("weave_closed")
        state = parent.request_payload.get("interpretation", {})
        if (state.get("execution_id") != str(child.pk) or state.get("revision") != data["revision"] or
                source_digest(state.get("sources", [])) != digest):
            raise InterpretationError("superseded")
        if (not child.cloud_approved or not gate.get("cloud_approved") or
            gate.get("source_digest") != digest or gate.get("revision") != data["revision"] or
            approval.get("source_digest") != digest or approval.get("revision") != data["revision"] or
            approval.get("weave_action_run_id") != str(parent.pk) or
            approval.get("execution_action_run_id") != str(child.pk) or
            approval.get("author_id") != child.initiator_id or approval.get("capability") != reading.capability):
            raise InterpretationError("cloud_approval_required")
        author = get_user_model().objects.get(pk=child.initiator_id)
        if not author.has_perm("initiatives.approve_cloud_dispatch"):
            raise InterpretationError("cloud_approval_not_permitted")
        runtime = person_runtime(author, reading=reading)
        from claude.service import run_blocking
        result = run_blocking(data["prompt"], cwd=runtime.home_dir,
            run_as_user=runtime.linux_user, home_dir=runtime.home_dir, timeout=180, tools="")
        if result.failure:
            raise InterpretationError(result.failure if result.failure in {"auth_failure", "timeout"} else "execution_failed")
        parsed = json.loads(result.output or "")
        reading.validate_findings(parsed, data["sources"])
        ActionRun.objects.filter(pk=child.pk).update(status=ActionRunStatus.SUCCEEDED,
            result_payload={"result": {"findings": parsed, "provenance": {
                "provider": "anthropic-claude-code", "model": None,
                "prompt_version": reading.prompt_version, "elapsed_ms": result.elapsed_ms,
                "usage": result.usage}}}, completed_at=timezone.now())
        apply_fn(str(child.pk))
    except InterpretationError as exc:
        fail(child.pk, exc.code, apply_fn=apply_fn)
    except (ValueError, TypeError, KeyError, ValidationError):
        fail(child.pk, "invalid_output", apply_fn=apply_fn)
    except Exception:
        fail(child.pk, "execution_failed", apply_fn=apply_fn)


def apply_interpretation(action_run_id, *, reading: Reading):
    child = ActionRun.objects.filter(pk=action_run_id, tool_name=f"capability.{reading.capability}").first()
    if child is None or child.parent_action_id is None:
        return
    with transaction.atomic():
        parent = ActionRun.objects.select_for_update().get(pk=child.parent_action_id)
        state = copy.deepcopy((parent.request_payload or {}).get("interpretation", {}))
        if (parent.status != ActionRunStatus.PENDING or parent.initiator_id != child.initiator_id or
            state.get("execution_id") != str(child.pk) or
            state.get("revision") != (child.request_payload or {}).get("revision")):
            return  # A stale completion remains on its child for audit; it never replaces newer findings.
        if child.status == ActionRunStatus.FAILED:
            state.update(status="failed", error=(child.error_payload or {}).get("error", "execution_failed"))
        elif child.status == ActionRunStatus.SUCCEEDED:
            try:
                result = (child.result_payload or {})["result"]
                findings = result["findings"]
                reading.validate_findings(findings, state["sources"])
                provenance = result["provenance"]
                if not isinstance(provenance, dict):
                    raise ValueError("Invalid provenance")
                state.update(status="succeeded", error=None, findings={
                    **findings, "revision": state["revision"],
                    "source_digest": source_digest(state["sources"]),
                    "execution_action_run_id": str(child.pk),
                    # Candidates are deliberately unresolved until an authorized resolver supplies them (D6).
                    "resolution": {s["sighting_id"]: {"status": "unresolved", "candidates": []}
                        for s in findings["sightings"] if s["shape_id"] in reading.resolvable_shape_ids},
                    "provenance": {"provider": provenance.get("provider", "inkwell"),
                        "model": provenance.get("model"), "prompt_version": reading.prompt_version,
                        "elapsed_ms": provenance.get("elapsed_ms"), "usage": provenance.get("usage"),
                        "contract_version": reading.version, "units": {unit: reading.version for unit in reading.units}}})
            except (KeyError, TypeError, ValueError, ValidationError):
                state.update(status="failed", error="invalid_output", findings=None)
                ActionRun.objects.filter(pk=child.pk).update(status=ActionRunStatus.FAILED,
                    result_payload=None, error_payload={"error": "invalid_output"})
        else:
            return
        parent.request_payload = {**parent.request_payload, "interpretation": state}
        parent.save(update_fields=["request_payload", "updated_at"])
