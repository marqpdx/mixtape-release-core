# atrium/turns.py
"""
Dialogue turns on the runtime worker, as the Dialogue owner's own account (ST-3 Part B).

The API calls start_turn(): it saves the person's words, creates the reply pending
with an ActionRun, and queues run_dialogue_turn on the runtime queue. The runtime
worker (the only one allowed to run a CLI as a person's Linux user) calls run_turn():
one process per turn, resuming the provider's own session, writing the reply into
its entry as it arrives and announcing each piece through atrium.relay. Nothing is
kept running between turns, and no Atrium path uses the server's login or an API key.

Which agent answers is chosen per message (Claude Code or Codex). Each provider's own
session is a cache: a provider returning to a Dialogue is first told what was said
since its last turn, by the person and by other agents (build_catch_up_prompt).
Distill and the Continuous Keeper's summaries run the same way, on the owner's account.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from cloud_agents.constants import PROVIDER_ANTHROPIC_CLAUDE_CODE, PROVIDER_OPENAI_CODEX

logger = logging.getLogger(__name__)

CAPABILITY = "atrium.dialogue"
TOOL_NAME = "atrium.dialogue"
DIALOGUE_PROVIDERS = (PROVIDER_ANTHROPIC_CLAUDE_CODE, PROVIDER_OPENAI_CODEX)

# How often a streaming reply is written to its entry and announced.
_FLUSH_SECONDS = 0.25

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_NAMESPACE = "platform:crossroads"


class TurnStop(RuntimeError):
    """A turn that stops with a reason the page can name (code)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def runtime_provider(provider: str) -> str:
    """The tenant_runtime provider for a Dialogue provider."""
    from tenant_runtime.resolve import CLAUDE, CODEX

    if provider == PROVIDER_ANTHROPIC_CLAUDE_CODE:
        return CLAUDE
    if provider == PROVIDER_OPENAI_CODEX:
        return CODEX
    raise TurnStop("provider_not_supported")


def owner_runtime(dialogue, provider: str):
    """The Dialogue owner's ready runtime for this provider, or TurnStop with its reason."""
    from tenant_runtime.resolve import RuntimeUnavailable, person_runtime

    user = getattr(dialogue.member, "user", None)
    if user is None:
        raise TurnStop("runtime_missing")
    try:
        return person_runtime(user, CAPABILITY, runtime_provider(provider))
    except RuntimeUnavailable as exc:
        raise TurnStop(exc.code) from exc


def dialogue_dir(dialogue) -> str:
    """
    The Dialogue's working directory: the same path on every turn.

    Claude Code keeps its sessions per working directory, so resuming needs the same
    path each time. The directory itself is empty and only needs to be enterable by
    the runtime user (the run has read-only tools); recreated if missing, for example
    after a worker restart clears a private /tmp. The session file the CLI keeps lives
    in the person's own home, not here.
    """
    root = getattr(settings, "ATRIUM_DIALOGUE_ROOT", "") or os.path.join(tempfile.gettempdir(), "atrium-dialogues")
    path = os.path.join(root, str(dialogue.id))
    os.makedirs(path, exist_ok=True)
    os.chmod(root, 0o755)
    os.chmod(path, 0o755)
    return path


def _new_action_run(dialogue, user, provider: str, reply_id) -> "ActionRun":
    from initiatives.models import (
        ActionRun,
        ActionRunExecutionMode,
        ActionRunInitiatorType,
        ActionRunStatus,
    )

    return ActionRun.objects.create(
        initiative_id=dialogue.initiative_id,
        tool_name=TOOL_NAME,
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD,
        service_name="atrium",
        tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)),
        tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE)),
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        # Sending a message to an agent in Atrium is the person's own approval of
        # this one call, on their own account.
        cloud_approved=True,
        approval_payload={"approved_by": "person", "how": "sent in an Atrium Dialogue"},
        request_payload={
            "dialogue_id": str(dialogue.id),
            "entry_id": str(reply_id),
            "provider": provider,
        },
    )


def _finish_action_run(action_run, *, ok: bool, result=None, error=None) -> None:
    from initiatives.models import ActionRunStatus

    if action_run is None:
        return
    action_run.status = ActionRunStatus.SUCCEEDED if ok else ActionRunStatus.FAILED
    action_run.result_payload = result
    action_run.error_payload = error
    action_run.completed_at = timezone.now()
    action_run.save(update_fields=["status", "result_payload", "error_payload", "completed_at", "updated_at"])


def _fail_entry(entry, code: str) -> None:
    from atrium import relay
    from atrium.models import DialogueEntryStatus

    entry.status = DialogueEntryStatus.FAILED
    entry.error_code = code
    entry.save(update_fields=["status", "error_code", "updated_at"])
    relay.notify(entry.id)


# ---------------------------------------------------------------------------
# In the API
# ---------------------------------------------------------------------------

def start_turn(dialogue, user, message: str, provider: str | None = None):
    """
    Save the person's message and queue the reply on the runtime worker.

    Returns the reply entry, pending; or failed with its reason (no account, signed
    out, not allowed) when the owner's runtime can't take it, in which case nothing
    is queued and the person's message is still kept.
    """
    from atrium.ai.service import _trigger_idle_keeper_if_due
    from atrium.models import DialogueEntry, DialogueEntryStatus, DialogueRole

    provider = provider or dialogue.ai_provider
    if provider not in DIALOGUE_PROVIDERS:
        provider = PROVIDER_ANTHROPIC_CLAUDE_CODE

    _trigger_idle_keeper_if_due(dialogue)

    DialogueEntry.objects.create(
        dialogue=dialogue,
        role=DialogueRole.USER,
        content=message,
        status=DialogueEntryStatus.DONE,
    )
    reply = DialogueEntry.objects.create(
        dialogue=dialogue,
        role=DialogueRole.ASSISTANT,
        speaker=provider,
        status=DialogueEntryStatus.PENDING,
    )

    update_fields = ["last_activity_at", "updated_at"]
    dialogue.last_activity_at = timezone.now()
    if dialogue.ai_provider != provider:
        dialogue.ai_provider = provider
        update_fields.append("ai_provider")
    if not dialogue.title:
        dialogue.title = message[:80]
        update_fields.append("title")
    dialogue.save(update_fields=update_fields)

    try:
        owner_runtime(dialogue, provider)
    except TurnStop as stop:
        _fail_entry(reply, stop.code)
        return reply

    action_run = _new_action_run(dialogue, user, provider, reply.id)
    reply.action_run = action_run
    reply.save(update_fields=["action_run", "updated_at"])

    from atrium.tasks import run_dialogue_turn

    transaction.on_commit(lambda: run_dialogue_turn.apply_async(
        kwargs={"entry_id": str(reply.id)}, queue="runtime", routing_key="runtime",
    ))
    return reply


# ---------------------------------------------------------------------------
# On the runtime worker
# ---------------------------------------------------------------------------

def _provider_events(provider: str, prompt: str, *, cwd: str, runtime, resume_id: str | None):
    if provider == PROVIDER_ANTHROPIC_CLAUDE_CODE:
        from claude import service as claude_service

        yield from claude_service.stream_turn(
            prompt,
            cwd=cwd,
            run_as_user=runtime.linux_user,
            home_dir=runtime.home_dir,
            tools=claude_service.READ_ONLY_TOOLS,
            resume_session_id=resume_id,
        )
    else:
        from codex import service as codex_service

        yield from codex_service.stream_exec(
            prompt,
            cwd=cwd,
            run_as_user=runtime.linux_user,
            home_dir=runtime.home_dir,
            policy="read_only",
            provider_session_id=resume_id,
        )


def _signed_out(provider: str, runtime, errors: list[str]) -> bool:
    """After a failed turn: is the account signed out? Settings then says so at once."""
    if provider == PROVIDER_ANTHROPIC_CLAUDE_CODE:
        from tenant_runtime.tasks import verify_claude_runtime

        return verify_claude_runtime(runtime) == "needs_sign_in"
    return any("auth" in (e or "").lower() for e in errors)


def run_turn(entry_id: str) -> str:
    """Write one reply. Returns its final status."""
    from atrium import relay
    from atrium.ai.service import build_catch_up_prompt, build_opening_prompt, latest_checkpoint, _parse_document_envelope
    from atrium.models import (
        CloudAgentSession,
        CloudAgentSessionStatus,
        DialogueEntry,
        DialogueEntryStatus,
        DialogueRole,
    )

    try:
        reply = DialogueEntry.objects.select_related("dialogue", "dialogue__member", "action_run").get(pk=entry_id)
    except DialogueEntry.DoesNotExist:
        logger.error("[atrium] turn entry %s not found", entry_id)
        return "missing"
    if reply.status != DialogueEntryStatus.PENDING:
        logger.info("[atrium] turn entry %s already %s; skipping", entry_id, reply.status)
        return reply.status

    dialogue = reply.dialogue
    provider = reply.speaker
    action_run = reply.action_run

    person_entry = (
        DialogueEntry.objects.filter(dialogue=dialogue, role=DialogueRole.USER, created_at__lte=reply.created_at)
        .order_by("-created_at")
        .first()
    )
    if person_entry is None:
        _fail_entry(reply, "failed")
        _finish_action_run(action_run, ok=False, error={"code": "failed", "message": "No message to answer."})
        return "failed"

    try:
        runtime = owner_runtime(dialogue, provider)
    except TurnStop as stop:
        _fail_entry(reply, stop.code)
        _finish_action_run(action_run, ok=False, error={"code": stop.code})
        return "failed"

    agent, _ = CloudAgentSession.objects.get_or_create(
        dialogue=dialogue,
        provider=provider,
        deleted_at__isnull=True,
        defaults={"linux_user": runtime.linux_user, "status": CloudAgentSessionStatus.STARTING},
    )
    if agent.linux_user != runtime.linux_user:
        # A different account now: its saved session isn't reachable; start fresh.
        agent.linux_user = runtime.linux_user
        agent.provider_session_id = ""
        agent.seen_through = None
    checkpoint = latest_checkpoint(dialogue, before=person_entry.created_at)
    if checkpoint and agent.seen_through and checkpoint.created_at > agent.seen_through:
        # Compacted since this agent's last turn: a fresh session, from the checkpoint.
        agent.provider_session_id = ""
        agent.seen_through = None
    cwd = dialogue_dir(dialogue)
    agent.working_directory = cwd
    agent.status = CloudAgentSessionStatus.RUNNING
    agent.last_used_at = timezone.now()
    agent.save()

    if action_run is not None:
        from initiatives.models import ActionRunStatus

        action_run.status = ActionRunStatus.RUNNING
        action_run.save(update_fields=["status", "updated_at"])

    reply.status = DialogueEntryStatus.STREAMING
    reply.save(update_fields=["status", "updated_at"])
    relay.notify(reply.id)

    def attempt(resume_id: str | None):
        if resume_id and agent.seen_through:
            prompt = build_catch_up_prompt(
                dialogue, person_entry.content, since=agent.seen_through, before=person_entry.created_at,
            )
        else:
            prompt, _note = build_opening_prompt(dialogue, person_entry.content, before=person_entry.created_at)
        chunks: list[str] = []
        errors: list[str] = []
        context: dict | None = None
        last_flush = time.monotonic()
        for event_type, text in _provider_events(provider, prompt, cwd=cwd, runtime=runtime, resume_id=resume_id):
            if event_type == "provider_session":
                if text and agent.provider_session_id != text:
                    agent.provider_session_id = text
                    agent.save(update_fields=["provider_session_id", "updated_at"])
            elif event_type == "delta":
                chunks.append(text)
                if time.monotonic() - last_flush >= _FLUSH_SECONDS:
                    reply.content = "".join(chunks)
                    reply.save(update_fields=["content", "updated_at"])
                    relay.notify(reply.id)
                    last_flush = time.monotonic()
            elif event_type in ("error", "auth_failure"):
                errors.append(text)
            elif event_type == "context_status":
                context = {"raw": text}
        return "".join(chunks), errors, context

    resume_id = agent.provider_session_id or None
    text, errors, context = attempt(resume_id)
    if resume_id and errors and not text:
        # The saved session couldn't be resumed (gone, or another machine's): start
        # this provider fresh from the Dialogue's own record, once.
        logger.warning("[atrium] resume failed for Dialogue %s (%s); starting fresh", dialogue.id, provider)
        agent.provider_session_id = ""
        agent.seen_through = None
        agent.save(update_fields=["provider_session_id", "seen_through", "updated_at"])
        text, errors, context = attempt(None)

    if errors or not text.strip():
        code = "runtime_not_ready" if _signed_out(provider, runtime, errors) else "failed"
        reply.content = text
        reply.status = DialogueEntryStatus.FAILED
        reply.error_code = code
        reply.save(update_fields=["content", "status", "error_code", "updated_at"])
        relay.notify(reply.id)
        agent.status = CloudAgentSessionStatus.FAILED
        agent.save(update_fields=["status", "updated_at"])
        _finish_action_run(action_run, ok=False, error={"code": code, "messages": [e[:300] for e in errors]})
        logger.warning("[atrium] turn failed Dialogue=%s provider=%s code=%s", dialogue.id, provider, code)
        return "failed"

    entry_type, doc_title, body = _parse_document_envelope(text)
    reply.content = body
    reply.entry_type = entry_type
    reply.document_title = doc_title
    reply.status = DialogueEntryStatus.DONE
    reply.save(update_fields=["content", "entry_type", "document_title", "status", "updated_at"])
    relay.notify(reply.id)

    agent.status = CloudAgentSessionStatus.READY
    agent.seen_through = reply.created_at
    agent.last_used_at = timezone.now()
    agent.save(update_fields=["status", "seen_through", "last_used_at", "updated_at"])

    dialogue.last_activity_at = timezone.now()
    dialogue.save(update_fields=["last_activity_at", "updated_at"])
    _finish_action_run(
        action_run,
        ok=True,
        result={"entry_id": str(reply.id), "provider": provider, "chars": len(body), "context": context},
    )
    return "done"


# ---------------------------------------------------------------------------
# One-off runs on the owner's account: Distill and the Keeper's summary
# ---------------------------------------------------------------------------

def run_once(dialogue, prompt: str, *, timeout: int = 180) -> str:
    """
    One prompt, no tools, no saved session, on the Dialogue owner's own Claude account.
    Raises TurnStop with a reason when it can't run or returns nothing.
    """
    from claude import service as claude_service

    runtime = owner_runtime(dialogue, PROVIDER_ANTHROPIC_CLAUDE_CODE)
    result = claude_service.run_blocking(
        prompt,
        timeout=timeout,
        run_as_user=runtime.linux_user,
        home_dir=runtime.home_dir,
        tools=claude_service.NO_TOOLS,
        log_context={"phase": "atrium-once", "dialogue": str(dialogue.id)},
    )
    if result.output:
        return result.output
    if result.failure == "auth_failure" or _signed_out(PROVIDER_ANTHROPIC_CLAUDE_CODE, runtime, []):
        raise TurnStop("runtime_not_ready")
    raise TurnStop("failed", result.failure or "empty")
