"""The shared interpretation lifecycle (ADR-0061, HD-2/HD-3): begin,
correct, execute, snapshot. Extracted from Shuttle's own
shuttle/interpretation/lifecycle.py (ADR-0058, SH-11), which built this
first; Shuttle is this module's first caller, wired through its own
thin wrapper so its tests and call sites are unchanged.

A surface's own identity (what a "parent" ActionRun is, how its raw
source is found and bounded) stays with the surface — only the
interpretation step state once a reading has begun (revision, sources,
status, execution bookkeeping) is generic here (D3, D4).
"""
from __future__ import annotations

import copy
import hashlib
from uuid import uuid4
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from initiatives.models import ActionRun, ActionRunStatus, ActionRunExecutionMode, ActionRunInitiatorType
from mixtape.celery_app import app as celery_app
from tenant_runtime.models import TenantClaudeRuntime

from .contract import Reading, source_digest
from .errors import InterpretationError


def owned_parent(action_run_id, author, *, tool_name, lock=False, allow_abandoned=False):
    qs = ActionRun.objects.select_for_update() if lock else ActionRun.objects
    run = qs.filter(pk=action_run_id, tool_name=tool_name,
                    initiator_id=str(author.pk)).first()
    if run is None:
        raise InterpretationError("not_found", 404)
    allowed = {ActionRunStatus.PENDING} | ({ActionRunStatus.ABANDONED} if allow_abandoned else set())
    if run.status not in allowed:
        raise InterpretationError("weave_closed", 409)
    if "interpretation" not in (run.request_payload or {}):
        raise InterpretationError("not_found", 404)
    return run


def person_runtime(author, *, reading: Reading):
    runtime = TenantClaudeRuntime.objects.filter(
        tenant_content_type=ContentType.objects.get_for_model(get_user_model()),
        tenant_object_id=author.pk).first()
    if runtime is None:
        raise InterpretationError("runtime_missing", 409)
    if runtime.status != TenantClaudeRuntime.STATUS_READY or not runtime.linux_user or not runtime.home_dir:
        raise InterpretationError("runtime_not_ready", 409)
    if reading.capability not in (runtime.allowed_ai_modes or []):
        raise InterpretationError("mode_not_allowed", 403)
    return runtime


def snapshot(parent, *, reading: Reading):
    state = parent.request_payload["interpretation"]
    child = parent.child_actions.filter(pk=state.get("execution_id")).first() if state.get("execution_id") else None
    status = state["status"]
    error = state.get("error")
    if parent.status == ActionRunStatus.ABANDONED:
        status, error = "abandoned", None
    elif child and child.status == ActionRunStatus.FAILED:
        status, error = "failed", (child.error_payload or {}).get("error", "execution_failed")
    elif child and child.status == ActionRunStatus.RUNNING and status == "pending":
        status = "running"
    return {"contract_version": reading.version, "weave_action_run_id": str(parent.pk),
            "execution_action_run_id": str(child.pk) if child else None,
            "revision": state["revision"], "source_digest": source_digest(state["sources"]),
            "sources": state["sources"], "status": status, "error": error,
            "findings": state.get("findings"),
            "cloud_requested": bool(getattr(settings, reading.cloud_setting_name, True))}


@transaction.atomic
def begin(*, author, request_id, reading: Reading, parent_factory, source_ref, source_text,
          conflict_key, conflict_value):
    """`parent_factory()` creates the surface's own parent ActionRun
    (Shuttle: `start_weave`) and is called only when no envelope for
    this request_id already exists — a duplicate HTTP request must
    never create a second envelope. `conflict_key`/`conflict_value` is
    the generic stand-in for Shuttle's own seed_id, stored under its own
    name on the interpretation state (so a surface's other code, e.g.
    Shuttle's `abandon_weave` reading `seed_id` directly, keeps working
    unchanged) and checked separately from `source_ref` (the sources
    list's own reference string): a request_id reused against a
    different source is a conflict, not a replay."""
    get_user_model().objects.select_for_update().get(pk=author.pk)
    existing = ActionRun.objects.filter(tool_name=reading.tool_name, initiator_id=str(author.pk),
        request_payload__interpretation__request_id=str(request_id)).first()
    if existing:
        if existing.request_payload["interpretation"].get(conflict_key) != conflict_value:
            raise InterpretationError("request_conflict", 409)
        return existing, snapshot(existing, reading=reading)
    parent = parent_factory()
    parent.request_payload["interpretation"] = {
        "request_id": str(request_id), conflict_key: conflict_value, "revision": 0,
        "sources": [{"source_ref": source_ref, "source_revision": 0, "text": source_text}],
        "status": "awaiting_cloud_approval" if getattr(settings, reading.cloud_setting_name, True) else "pending",
        "requests": {}, "execution_id": None, "findings": None, "error": None}
    parent.save(update_fields=["request_payload", "updated_at"])
    return parent, snapshot(parent, reading=reading)


@transaction.atomic
def correct(*, author, action_run_id, request_id, expected_revision, reading: Reading,
            text, source_ref_prefix="correction"):
    parent = owned_parent(action_run_id, author, tool_name=reading.tool_name, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    key = f"correction:{request_id}"
    if not text or not text.strip() or len(text) > 12000:
        raise InterpretationError("invalid_correction")
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key in state["requests"]:
        if state["requests"][key]["fingerprint"] != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return snapshot(parent, reading=reading)
    if state["revision"] != expected_revision:
        raise InterpretationError("revision_conflict", 409)
    if len(state["sources"]) >= 12 or sum(len(s["text"]) for s in state["sources"]) + len(text) > 40000:
        raise InterpretationError("source_too_long", 413)
    state["revision"] += 1
    state["sources"].append({"source_ref": f"{source_ref_prefix}:{request_id}",
        "source_revision": state["revision"], "text": text})
    state["requests"][key] = {"revision": state["revision"], "fingerprint": fingerprint}
    state["status"] = "awaiting_cloud_approval" if getattr(settings, reading.cloud_setting_name, True) else "pending"
    state["execution_id"], state["error"] = None, None
    # Prior findings are prompt context only; never present them as this revision's result.
    state["previous_findings"], state["findings"] = state.get("findings") or state.get("previous_findings"), None
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])
    return snapshot(parent, reading=reading)


def _enqueue(child_id, kwargs):
    try:
        celery_app.send_task("switchboard.capability_async", kwargs=kwargs, queue="switchboard")
    except Exception:
        ActionRun.objects.filter(pk=child_id, status=ActionRunStatus.PENDING).update(
            status=ActionRunStatus.FAILED, error_payload={"error": "dispatch_unavailable"},
            completed_at=timezone.now())


@transaction.atomic
def execute(*, author, action_run_id, request_id, expected_revision, digest, reading: Reading, consent=False):
    parent = owned_parent(action_run_id, author, tool_name=reading.tool_name, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    key = f"execution:{request_id}"
    if key in state["requests"]:
        return snapshot(parent, reading=reading)
    if state["revision"] != expected_revision or source_digest(state["sources"]) != digest:
        raise InterpretationError("revision_conflict", 409)
    if state.get("execution_id") and parent.child_actions.filter(pk=state["execution_id"],
            status__in=[ActionRunStatus.PENDING, ActionRunStatus.RUNNING]).exists():
        raise InterpretationError("execution_in_progress", 409)
    cloud = bool(getattr(settings, reading.cloud_setting_name, True))
    if cloud:
        if not consent:
            raise InterpretationError("cloud_approval_required", 403)
        if not author.has_perm("initiatives.approve_cloud_dispatch"):
            raise InterpretationError("cloud_approval_not_permitted", 403)
        person_runtime(author, reading=reading)  # Readiness gate; rechecked immediately before the actual call.
    child_id = uuid4()
    approval = {"author_id": str(author.pk), "weave_action_run_id": str(parent.pk),
        "execution_action_run_id": str(child_id), "revision": state["revision"],
        "source_digest": digest, "capability": reading.capability, "approved_at": timezone.now().isoformat()}
    capability_payload = {"sources": state["sources"],
        "previous_findings": state.get("previous_findings"), "source_ref": f"{reading.tool_name}:{parent.pk}",
        "prompt": reading.build_prompt(state["sources"], state.get("previous_findings")),
        "response_schema": reading.response_schema, "source_digest": digest, "revision": state["revision"]}
    child = ActionRun.objects.create(id=child_id, tool_name=f"capability.{reading.capability}",
        parent_action=parent, service_name="switchboard", status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD if cloud else ActionRunExecutionMode.LOCAL,
        tenant_id=parent.tenant_id, tenant_namespace=parent.tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN, initiator_id=str(author.pk),
        cloud_approved=cloud, approval_payload=approval if cloud else None,
        request_payload={"capability_payload": capability_payload, "revision": state["revision"],
            "source_digest": digest, "prompt_version": reading.prompt_version, "cloud_requested": cloud})
    state.update(status="pending", execution_id=str(child.pk), error=None)
    state["requests"][key] = str(child.pk)
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])
    kwargs = {"action_run_id": str(child.pk), "tenant_id": str(parent.tenant_id),
        "tenant_namespace": parent.tenant_namespace, "principal_user_id": str(author.pk),
        "principal_service_token_id": None, "capability": reading.capability,
        "capability_payload": capability_payload, "cloud_mode": cloud,
        "escalation_approved": cloud, "callback_task": reading.callback_task,
        "callback_queue": reading.callback_queue}
    transaction.on_commit(lambda: _enqueue(str(child.pk), kwargs))
    return snapshot(parent, reading=reading)
