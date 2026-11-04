"""Ordered actual attempts stored in the reading parent's existing payload.

No database or routing layer is introduced. advance() performs deterministic
work up to the next model boundary; the lifecycle dispatches that real call.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone
from jsonschema import ValidationError

from .bundle import digest, bundle_identity
from .errors import InterpretationError
from .validation import validate_result


@dataclass(frozen=True)
class Step:
    id: str
    version: str
    kind: str
    input_contract: str
    output_contract: str
    requires: tuple[str, ...] = ()
    required: bool = True
    run: Callable | None = None
    validate: Callable | None = None
    should_run: Callable | None = None
    build_prompt: Callable | None = None
    response_schema: dict | None = None


def definitions(reading):
    seen = set()
    for step in reading.steps:
        if (not step.id or not step.version or step.id in seen or
                step.kind not in {"deterministic", "model"} or
                not set(step.requires) <= seen or not step.input_contract or not step.output_contract):
            raise ValueError("Invalid ordered Heddle Step definition")
        if step.kind == "deterministic" and step.run is None:
            raise ValueError("Deterministic Step requires a run hook")
        if step.kind == "model" and (step.build_prompt is None or step.response_schema is None):
            raise ValueError("Model Step requires a prompt hook and response schema")
        seen.add(step.id)
    return [{"id": s.id, "version": s.version, "kind": s.kind,
             "input_contract": s.input_contract, "output_contract": s.output_contract,
             "requires": list(s.requires), "required": s.required,
             "response_schema_digest": digest(s.response_schema) if s.response_schema is not None else None} for s in reading.steps]


def context_snapshot(reading, author, parent):
    if reading.context_provider is None:
        raise InterpretationError("context_provider_required")
    context = copy.deepcopy(reading.context_provider(author, parent))
    if not isinstance(context, dict) or type(context.get("revision")) is not int or context["revision"] < 0:
        raise InterpretationError("invalid_context")
    return context


def identity(state):
    from .contract import source_digest
    return {"revision": state["revision"], "source_digest": source_digest(state["sources"]),
            "context_revision": state["context"]["revision"], "context_digest": digest(state["context"])}


def plan_identity(reading):
    return {"contract_version": reading.version, "prompt_version": reading.prompt_version,
            "strategy_id": reading.strategy_id, "strategy_version": reading.strategy_version,
            "steps_digest": digest(definitions(reading)), "bundle_digest": bundle_identity()["digest"],
            "reference_fields_digest": digest(reading.reference_fields)}


def assert_current(reading, state, author, parent):
    if digest(context_snapshot(reading, author, parent)) != digest(state["context"]):
        raise InterpretationError("context_conflict", 409)
    if state.get("plan") != plan_identity(reading):
        raise InterpretationError("definition_conflict", 409)


def archive(state):
    """Retain every attempt/Sighting when source or context is superseded/retried."""
    if state.get("steps") or state.get("findings"):
        state.setdefault("history", []).append({
            **identity(state), "attempt_id": state.get("attempt_id"), "status": "superseded", "previous_status": state["status"],
            "steps": copy.deepcopy(state.get("steps", [])), "findings": state.get("findings"),
            "execution_id": state.get("execution_id"), "plan": state.get("plan"),
            "context": copy.deepcopy(state.get("context")),
            "sources": copy.deepcopy(state.get("sources", []))})
    state["steps"] = []


def initialize(reading, state, request_id):
    archive(state)
    state["plan"] = plan_identity(reading)
    state["attempt_id"] = str(request_id)
    state["steps"] = [{**d, **identity(state), "attempt_id": str(request_id),
        "status": "pending", "started_at": None, "completed_at": None,
        "execution_action_run_id": None, "input_digest": None, "output_digest": None,
        "output": None, "error": None} for d in definitions(reading)]
    state.update(status="running", findings=None, error=None, execution_id=None)


def inputs(state):
    return {"sources": copy.deepcopy(state["sources"]), "context": copy.deepcopy(state["context"]),
            "outputs": {s["id"]: copy.deepcopy(s["output"]) for s in state["steps"] if s["status"] == "succeeded"}}


def failed(state, record, code):
    record.update(status="failed", error={"code": code}, completed_at=timezone.now().isoformat())
    state.update(status="partial" if any(s["status"] == "succeeded" for s in state["steps"]) else "failed",
                 error=code, execution_id=None)
    # Actual failure halts this attempt. An explicit retry creates a new attempt.
    for later in state["steps"]:
        if later["status"] == "pending":
            later.update(status="not_attempted", error={"code": "prior_step_failed"})


def accept_output(step, record, output):
    if not isinstance(output, dict):
        raise ValidationError("Step output must be an object")
    if step.validate:
        step.validate(output)
    record.update(status="succeeded", output=copy.deepcopy(output), output_digest=digest(output),
                  completed_at=timezone.now().isoformat(), error=None)


def advance(reading, state):
    for step, record in zip(reading.steps, state["steps"]):
        if record["status"] != "pending":
            continue
        by_id = {r["id"]: r for r in state["steps"]}
        if any(by_id[r]["status"] != "succeeded" for r in step.requires):
            record.update(status="not_attempted", error={"code": "prerequisite_unavailable"})
            continue
        data = inputs(state)
        record.update(input_digest=digest(data), started_at=timezone.now().isoformat())
        try:
            if step.should_run and not step.should_run(data):
                record.update(status="skipped", completed_at=timezone.now().isoformat())
                continue
            if step.kind == "model":
                return step
            record["status"] = "running"
            output = step.run(data)
            if step is reading.steps[-1]:
                validate_result(reading, output, state["sources"])
            accept_output(step, record, output)
        except (InterpretationError, ValidationError, ValueError, TypeError, KeyError):
            failed(state, record, "invalid_step_output")
            return None
        except Exception:
            failed(state, record, "step_failed")
            return None
    if any(r["required"] and r["status"] != "succeeded" for r in state["steps"]):
        state.update(status="partial", error="required_step_incomplete")
        return None
    try:
        output = next(r["output"] for r in reversed(state["steps"]) if r["status"] == "succeeded")
        validate_result(reading, output, state["sources"])
        state.update(status="succeeded", findings=output, error=None, execution_id=None)
    except (StopIteration, ValidationError, TypeError, ValueError, KeyError):
        state.update(status="partial", error="invalid_output", findings=None)
    return None
