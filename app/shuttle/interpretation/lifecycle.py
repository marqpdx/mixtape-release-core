"""Author-scoped transient weave state; the approved envelope is the parent.

Thin Shuttle-specific wiring over Heddle's shared lifecycle (ADR-0061,
HD-2) — Shuttle is Heddle's first caller. Every function here keeps its
original signature and behavior so existing call sites
(`shuttle/api/views.py`) and tests are unchanged; only the generic
machinery underneath moved to `app/heddle/`.
"""
from __future__ import annotations

from heddle import lifecycle as heddle_lifecycle
from heddle.errors import InterpretationError  # noqa: F401 — re-exported; tests use lifecycle.InterpretationError
from mixtape.celery_app import app as celery_app  # noqa: F401 — kept so tests' `patch('shuttle.interpretation.lifecycle.celery_app.send_task')` resolves; heddle.lifecycle's _enqueue dispatches through the same singleton object.
from shuttle.services import start_weave
from writing.models import Seed

from .contract import SHUTTLE_READING


def owned_parent(action_run_id, author, lock=False, allow_abandoned=False):
    return heddle_lifecycle.owned_parent(action_run_id, author, tool_name=SHUTTLE_READING.tool_name,
        lock=lock, allow_abandoned=allow_abandoned)


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
    return heddle_lifecycle.person_runtime(author, reading=SHUTTLE_READING)


def snapshot(parent):
    return heddle_lifecycle.snapshot(parent, reading=SHUTTLE_READING)


def begin(*, author, request_id, seed_id, client):
    seed, text = source_from_seed(seed_id, author)

    def parent_factory():
        return start_weave(weave_in={"version": "1.0", "text": text,
            "client": client, "capture_mode": "voice" if seed.kind == "voice" else "typed"}, author=author)

    _, snap = heddle_lifecycle.begin(author=author, request_id=request_id, reading=SHUTTLE_READING,
        parent_factory=parent_factory, source_ref=f"seed:{seed_id}", source_text=text,
        conflict_key="seed_id", conflict_value=str(seed_id))
    return snap


def correct(*, author, action_run_id, request_id, expected_revision, text=None, seed_id=None):
    if seed_id is not None:
        _, text = source_from_seed(seed_id, author)
    return heddle_lifecycle.correct(author=author, action_run_id=action_run_id, request_id=request_id,
        expected_revision=expected_revision, reading=SHUTTLE_READING, text=text)


def execute(*, author, action_run_id, request_id, expected_revision, digest, consent=False):
    return heddle_lifecycle.execute(author=author, action_run_id=action_run_id, request_id=request_id,
        expected_revision=expected_revision, digest=digest, reading=SHUTTLE_READING, consent=consent)
