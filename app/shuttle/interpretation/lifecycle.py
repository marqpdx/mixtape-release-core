"""Author-scoped transient weave state; the approved envelope is the parent."""
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
from shuttle.services import start_weave
from tenant_runtime.models import TenantClaudeRuntime
from writing.models import Seed
from .contract import CAPABILITY, MODEL_SCHEMA, PROMPT_VERSION, VERSION, source_digest, build_prompt


class InterpretationError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def owned_parent(action_run_id, author, lock=False):
    qs = ActionRun.objects.select_for_update() if lock else ActionRun.objects
    run = qs.filter(pk=action_run_id, tool_name="shuttle.weave",
                    initiator_id=str(author.pk)).first()
    if run is None:
        raise InterpretationError("not_found", 404)
    if run.status != ActionRunStatus.PENDING:
        raise InterpretationError("weave_closed", 409)
    if "interpretation" not in (run.request_payload or {}):
        raise InterpretationError("not_found", 404)
    return run


def source_from_seed(seed_id, author):
    seed = Seed.objects.filter(pk=seed_id, author=author).first()
    if seed is None:
        raise InterpretationError("not_found", 404)
    text = seed.transcript_text if seed.kind == "voice" else seed.body_text
    if seed.status != "ready" or not text or not text.strip():
        raise InterpretationError("source_not_ready", 409)
    if len(text) > 24000:
        raise InterpretationError("source_too_long", 413)
    return seed, text


def person_runtime(author):
    runtime = TenantClaudeRuntime.objects.filter(
        tenant_content_type=ContentType.objects.get_for_model(get_user_model()),
        tenant_object_id=author.pk).first()
    if runtime is None:
        raise InterpretationError("runtime_missing", 409)
    if runtime.status != TenantClaudeRuntime.STATUS_READY or not runtime.linux_user or not runtime.home_dir:
        raise InterpretationError("runtime_not_ready", 409)
    if CAPABILITY not in (runtime.allowed_ai_modes or []):
        raise InterpretationError("mode_not_allowed", 403)
    return runtime


def snapshot(parent):
    state = parent.request_payload["interpretation"]
    child = parent.child_actions.filter(pk=state.get("execution_id")).first() if state.get("execution_id") else None
    status = state["status"]
    error = state.get("error")
    if child and child.status == ActionRunStatus.FAILED:
        status, error = "failed", (child.error_payload or {}).get("error", "execution_failed")
    elif child and child.status == ActionRunStatus.RUNNING and status == "pending":
        status = "running"
    return {"contract_version": VERSION, "weave_action_run_id": str(parent.pk),
            "execution_action_run_id": str(child.pk) if child else None,
            "revision": state["revision"], "source_digest": source_digest(state["sources"]),
            "sources": state["sources"], "status": status, "error": error,
            "findings": state.get("findings"),
            "cloud_requested": bool(getattr(settings, "SHUTTLE_INTERPRET_CLOUD", True))}


@transaction.atomic
def begin(*, author, request_id, seed_id, client):
    # Serialize this person's starts so duplicate HTTP requests cannot create two envelopes.
    get_user_model().objects.select_for_update().get(pk=author.pk)
    existing = ActionRun.objects.filter(tool_name="shuttle.weave", initiator_id=str(author.pk),
        request_payload__interpretation__request_id=str(request_id)).first()
    if existing:
        if existing.request_payload["interpretation"]["seed_id"] != str(seed_id):
            raise InterpretationError("request_conflict", 409)
        return snapshot(existing)
    seed, text = source_from_seed(seed_id, author)
    parent = start_weave(weave_in={"version": "1.0", "text": text,
        "client": client, "capture_mode": "voice" if seed.kind == "voice" else "typed"}, author=author)
    parent.request_payload["interpretation"] = {
        "request_id": str(request_id), "seed_id": str(seed_id), "revision": 0,
        "sources": [{"source_ref": f"seed:{seed_id}", "source_revision": 0, "text": text}],
        "status": "awaiting_cloud_approval" if getattr(settings, "SHUTTLE_INTERPRET_CLOUD", True) else "pending",
        "requests": {}, "execution_id": None, "findings": None, "error": None}
    parent.save(update_fields=["request_payload", "updated_at"])
    return snapshot(parent)


@transaction.atomic
def correct(*, author, action_run_id, request_id, expected_revision, text=None, seed_id=None):
    parent = owned_parent(action_run_id, author, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    key = f"correction:{request_id}"
    if seed_id is not None:
        _, text = source_from_seed(seed_id, author)
    if not text or not text.strip() or len(text) > 12000:
        raise InterpretationError("invalid_correction")
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key in state["requests"]:
        if state["requests"][key]["fingerprint"] != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return snapshot(parent)
    if state["revision"] != expected_revision:
        raise InterpretationError("revision_conflict", 409)
    if len(state["sources"]) >= 12 or sum(len(s["text"]) for s in state["sources"]) + len(text) > 40000:
        raise InterpretationError("source_too_long", 413)
    state["revision"] += 1
    state["sources"].append({"source_ref": f"correction:{request_id}",
        "source_revision": state["revision"], "text": text})
    state["requests"][key] = {"revision": state["revision"], "fingerprint": fingerprint}
    state["status"] = "awaiting_cloud_approval" if getattr(settings, "SHUTTLE_INTERPRET_CLOUD", True) else "pending"
    state["execution_id"], state["error"] = None, None
    # Prior findings are prompt context only; never present them as this revision's result.
    state["previous_findings"], state["findings"] = state.get("findings") or state.get("previous_findings"), None
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])
    return snapshot(parent)


def _enqueue(child_id, kwargs):
    try:
        celery_app.send_task("switchboard.capability_async", kwargs=kwargs, queue="switchboard")
    except Exception:
        ActionRun.objects.filter(pk=child_id, status=ActionRunStatus.PENDING).update(
            status=ActionRunStatus.FAILED, error_payload={"error": "dispatch_unavailable"},
            completed_at=timezone.now())


@transaction.atomic
def execute(*, author, action_run_id, request_id, expected_revision, digest, consent=False):
    parent = owned_parent(action_run_id, author, lock=True)
    state = copy.deepcopy(parent.request_payload["interpretation"])
    key = f"execution:{request_id}"
    if key in state["requests"]:
        return snapshot(parent)
    if state["revision"] != expected_revision or source_digest(state["sources"]) != digest:
        raise InterpretationError("revision_conflict", 409)
    if state.get("execution_id") and parent.child_actions.filter(pk=state["execution_id"],
            status__in=[ActionRunStatus.PENDING, ActionRunStatus.RUNNING]).exists():
        raise InterpretationError("execution_in_progress", 409)
    cloud = bool(getattr(settings, "SHUTTLE_INTERPRET_CLOUD", True))
    if cloud:
        if not consent:
            raise InterpretationError("cloud_approval_required", 403)
        if not author.has_perm("initiatives.approve_cloud_dispatch"):
            raise InterpretationError("cloud_approval_not_permitted", 403)
        person_runtime(author)  # Readiness gate; rechecked immediately before the actual call.
    child_id = uuid4()
    approval = {"author_id": str(author.pk), "weave_action_run_id": str(parent.pk),
        "execution_action_run_id": str(child_id), "revision": state["revision"],
        "source_digest": digest, "capability": CAPABILITY, "approved_at": timezone.now().isoformat()}
    capability_payload = {"sources": state["sources"],
        "previous_findings": state.get("previous_findings"), "source_ref": f"weave:{parent.pk}",
        "prompt": build_prompt(state["sources"], state.get("previous_findings")),
        "response_schema": MODEL_SCHEMA, "source_digest": digest, "revision": state["revision"]}
    child = ActionRun.objects.create(id=child_id, tool_name=f"capability.{CAPABILITY}",
        parent_action=parent, service_name="switchboard", status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD if cloud else ActionRunExecutionMode.LOCAL,
        tenant_id=parent.tenant_id, tenant_namespace=parent.tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN, initiator_id=str(author.pk),
        cloud_approved=cloud, approval_payload=approval if cloud else None,
        request_payload={"capability_payload": capability_payload, "revision": state["revision"],
            "source_digest": digest, "prompt_version": PROMPT_VERSION, "cloud_requested": cloud})
    state.update(status="pending", execution_id=str(child.pk), error=None)
    state["requests"][key] = str(child.pk)
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])
    kwargs = {"action_run_id": str(child.pk), "tenant_id": str(parent.tenant_id),
        "tenant_namespace": parent.tenant_namespace, "principal_user_id": str(author.pk),
        "principal_service_token_id": None, "capability": CAPABILITY,
        "capability_payload": capability_payload, "cloud_mode": cloud,
        "escalation_approved": cloud, "callback_task": "shuttle.apply_interpretation",
        "callback_queue": "catalyst"}
    transaction.on_commit(lambda: _enqueue(str(child.pk), kwargs))
    return snapshot(parent)
