"""Accepted recognition Strategy. Dictionary authority is a separate dependency.

No provider is registered until its owner supplies the reviewed Folio-scoped
snapshot. Missing authority refuses; it never manufactures an empty Dictionary.
"""
from copy import deepcopy
import json
import re
from pathlib import Path

import yaml
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from celery import shared_task

from folio.models import FolioNote, FolioInterpretation
from folio.services.interpretation import owned_folio
from heddle import steps
from heddle.bundle import _load, bundle_identity, digest
from heddle.contract import Reading
from heddle.errors import InterpretationError
from heddle.local import enabled
from initiatives.models import ActionRun
from . import recognition_contract as wire

CAPABILITY = "ariadne.recognize_mentions"
STRATEGY = "writing.fiction_note_recognition"
VERSION = "0.1.0"
_dictionary_provider = None


def register_dictionary_provider(provider):
    """Application wiring only; never selected by a request or deployment string."""
    global _dictionary_provider
    _dictionary_provider = provider


def dependencies():
    files = {p: e for p, e in _load()["files"].items() if p.startswith(("writing/", "shared/"))}
    if sum(len(e["text"]) for e in files.values()) > 80000:
        raise InterpretationError("dependency_too_large", 413)
    plan = yaml.safe_load(files["writing/strategies/fiction-note-recognition.strategy.yaml"]["text"])
    if (plan["id"], plan["version"]) != (STRATEGY, VERSION):
        raise InterpretationError("definition_conflict", 409)
    cues: list[tuple[str, str]] = []
    for name in ("character", "setting"):
        shape = yaml.safe_load(files[f"writing/{name}.shape.yaml"]["text"])
        if shape["version"] != "0.2.0":
            raise InterpretationError("definition_conflict", 409)
        cues.extend((f"writing.{name}", term) for term in shape["synonyms"])
    return {"bundle": bundle_identity(), "dependency_digest": digest(files), "cues": cues}


def authority(author, parent, state=None):
    if not author.is_active:
        raise InterpretationError("not_found", 404)
    refs = parent.request_payload["folio_source"]
    folio = owned_folio(author, refs["folio_id"])
    note = FolioNote.objects.filter(pk=refs["note_id"], folio=folio, deleted_at__isnull=True).first()
    if state is not None and not FolioInterpretation.objects.filter(action_run=parent,
            folio_note=note, initiated_by=author).exists():
        raise InterpretationError("note_moved_or_unavailable", 409)
    if note is None or note.status != "ready" or folio.work_type != "fiction":
        raise InterpretationError("source_not_ready", 409)
    if state is not None:
        if sum(len(s["text"]) for s in state["sources"]) > wire.PROFILE["max_source_chars"]:
            raise InterpretationError("source_too_long", 413)
        source = state["sources"][0]
        if source != {"source_ref": f"folio_note:{note.pk}", "source_revision": 0, "text": note.text}:
            raise InterpretationError("source_conflict", 409)
    return folio


def context_provider(author, parent):
    folio = authority(author, parent)
    if _dictionary_provider is None:
        raise InterpretationError("dictionary_unavailable", 503)
    dictionary = deepcopy(_dictionary_provider(author, folio))
    if (not isinstance(dictionary, dict) or set(dictionary) != {"revision", "entries"}
            or type(dictionary["revision"]) is not int or dictionary["revision"] < 0
            or not isinstance(dictionary["entries"], list)):
        raise InterpretationError("dictionary_unavailable", 503)
    pinned = dependencies()
    return {"revision": folio.context_revision, "folio_id": str(folio.pk),
        "work_type": folio.work_type, "title": folio.title, "title_is_writer_set": bool(folio.title),
        "local_only": folio.local_only, "bundle": pinned["bundle"],
        "dependency_digest": pinned["dependency_digest"], "dictionary": dictionary,
        "project_markers": [], "field_labels": []}


def prepare(data):
    if sum(len(s["text"]) for s in data["sources"]) > wire.PROFILE["max_source_chars"]:
        raise InterpretationError("source_too_long", 413)
    return {"sources_digest": digest(data["sources"]), "context_digest": digest(data["context"])}


def cues(data):
    result = []
    for source in data["sources"]:
        for shape, term in dependencies()["cues"]:
            for match in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source["text"], re.I):
                prefix = source["text"][max(0, match.start() - 32):match.start()]
                result.append({"shape_id": shape, "term": term, "source_locator": {
                    "source_ref": source["source_ref"], "source_revision": source["source_revision"],
                    "start": match.start(), "end": match.end(), "quote": match.group()},
                    "negated": bool(re.search(r"\b(?:not|isn't|isn’t|no)(?:\s+(?:a|an|the))?\s*$", prefix, re.I)),
                    "ambiguous": True})
    return {"cues": result}


def build_request(data, binding):
    request = {"protocol": wire.PROTOCOL, "profile_digest": wire.PROFILE_DIGEST,
        "binding": binding, "sources": data["sources"], "context": data["context"], "local_only": True}
    try:
        wire.validate_request(request)
    except wire.RecognitionError as exc:
        raise InterpretationError(exc.code, exc.status) from None
    return request


def checked(data):
    return {"scope": "recognition_only", "semantic_interpretation": "not_run",
        "cues": data["outputs"]["cue_recognition"]["cues"],
        "recognition": data["outputs"]["mention_recognition"]}


def validate_findings(result, sources):
    if (set(result) != {"scope", "semantic_interpretation", "cues", "recognition"}
            or result["scope"] != "recognition_only" or result["semantic_interpretation"] != "not_run"):
        raise ValueError("Invalid recognition coverage")
    return result


def make_reading():
    return Reading(capability=CAPABILITY, tool_name="folio.reading", version=VERSION,
        prompt_version=VERSION, units=("character", "setting"), cloud_setting_name="FOLIO_RECOGNITION_CLOUD",
        build_prompt=lambda *args: None, response_schema={}, validate_findings=validate_findings,
        resolvable_shape_ids=frozenset(), callback_task="folio.apply_recognition",
        context_provider=context_provider, strategy_id=STRATEGY, strategy_version=VERSION,
        local_enabled_setting="FOLIO_RECOGNITION_ENABLED", execution_guard=authority,
        steps=(steps.Step("source_context_preparation", VERSION, "deterministic", "source/1", "prepared/1", run=prepare),
            steps.Step("cue_recognition", VERSION, "deterministic", "prepared/1", "cues/1",
                requires=("source_context_preparation",), run=cues),
            steps.Step("mention_recognition", VERSION, "model", wire.PROTOCOL, wire.PROTOCOL,
                requires=("cue_recognition",), backend="local", build_request=build_request,
                validate_response=wire.validate_response, execution_identity=wire.PROFILE_DIGEST,
                response_schema=json.loads((Path(wire.ROOT) / "response.schema.json").read_text())),
            steps.Step("checked_recognition", VERSION, "deterministic", wire.PROTOCOL, "recognition/1",
                requires=("mention_recognition",), run=checked)))


@transaction.atomic
def claim(*, execution_id, person_id, tenant_id, tenant_namespace, request_fingerprint):
    from heddle.ordered import binding
    # Serialize on the same parent as execute/apply; then lock its child.
    ref = ActionRun.objects.filter(pk=execution_id, tool_name=f"capability.{CAPABILITY}").first()
    if ref is None or ref.parent_action_id is None:
        raise InterpretationError("not_found", 404)
    parent = ActionRun.objects.select_for_update().get(pk=ref.parent_action_id)
    child = ActionRun.objects.select_for_update().get(pk=ref.pk)
    if (child.initiator_id != str(person_id) or parent.initiator_id != str(person_id)
            or child.initiator_type != "human" or parent.initiator_type != "human"
            or str(child.tenant_id) != str(tenant_id) or str(parent.tenant_id) != str(tenant_id)
            or child.tenant_namespace != tenant_namespace or parent.tenant_namespace != tenant_namespace
            or child.execution_mode != "local" or child.cloud_approved
            or parent.tool_name != "folio.reading" or parent.status != "pending"):
        raise InterpretationError("not_found", 404)
    author = get_user_model().objects.filter(pk=person_id, is_active=True).first()
    if author is None:
        raise InterpretationError("not_found", 404)
    reading = make_reading()
    state = parent.request_payload.get("interpretation", {})
    steps.assert_current(reading, state, author, parent)
    record = next((r for r in state["steps"] if r["execution_action_run_id"] == str(child.pk)), None)
    payload = child.request_payload
    request = payload["capability_payload"]
    if (not record or record["status"] not in {"running", "succeeded", "failed"}
            or digest(request) != request_fingerprint or payload["request_fingerprint"] != request_fingerprint):
        raise InterpretationError("execution_conflict", 409)
    expected = {**binding(reading, state, record), "weave_action_run_id": str(parent.pk),
                "execution_action_run_id": str(child.pk)}
    if request != build_request(steps.inputs(state), expected):
        raise InterpretationError("execution_conflict", 409)
    if child.status in {"succeeded", "failed"} and payload.get("local_claimed"):
        return {"status": "terminal", "callback_task": reading.callback_task, "callback_queue": reading.callback_queue,
                "result": child.result_payload, "error": child.error_payload}
    if (child.status != "pending" or payload.get("local_claimed")
            or record["status"] != "running" or state["execution_id"] != str(child.pk)):
        raise InterpretationError("execution_unavailable", 409)
    try:
        enabled(reading)
    except InterpretationError as exc:
        # Current authority has been established. Record the denial only on
        # this still-pending child, so disabling a queued request cannot orphan it.
        child.request_payload = {**payload, "local_claimed": True}
        child.status = "failed"
        child.error_payload = {"error": exc.code}
        child.completed_at = timezone.now()
        child.save(update_fields=["request_payload", "status", "error_payload", "completed_at", "updated_at"])
        return {"status": "terminal", "callback_task": reading.callback_task, "callback_queue": reading.callback_queue,
                "result": None, "error": child.error_payload}
    child.request_payload = {**payload, "local_claimed": True}
    child.status = "running"
    child.save(update_fields=["request_payload", "status", "updated_at"])
    return {"status": "claimed", "request": request,
            "callback_task": reading.callback_task, "callback_queue": reading.callback_queue}


@shared_task(name="folio.apply_recognition")
def apply_recognition(action_run_id):
    from heddle.tasks import apply_interpretation
    return apply_interpretation(action_run_id, reading=make_reading())
