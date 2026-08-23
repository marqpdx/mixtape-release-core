# atrium/ai/service.py
#
# AI service for the Atrium personal session surface.
# Mirrors the adapter pattern from initiatives/ai/service.py.
#
# exchange_stream() yields SSE byte chunks for StreamingHttpResponse.
# The caller is responsible for saving AtriumSessionEntry records.
#
# Phase 2A dispatch:
#   ATRIUM_USE_CLAUDE_CODE=True  → ClaudeCodeAdapter (local claude -p subprocess)
#   default                       → AtriumAnthropicAdapter (Anthropic SDK, Phase 1)

import json
import logging
import os
from typing import Generator

from atrium.ai.tools import TOOLS, dispatch_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 6

# Groups that route through ClaudeCodeAdapter (Puddlejump cwd).
# Hard-coded for local use — VPS deployment is a separate ADR item.
PUDDLEJUMP_GROUPS: frozenset[str] = frozenset({"mindful-brilliance"})


class AtriumAnthropicAdapter:
    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 4096

    def __init__(self):
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def exchange_stream(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> Generator[bytes, None, None]:
        """
        Yields SSE-formatted byte chunks:
          data: {"type": "delta", "text": "..."}\n\n
          data: {"type": "done"}\n\n

        Runs Claude's tool_use loop internally (query_canon, get_document,
        read_file, grep — all read-only, see atrium/ai/tools.py) so the
        streamed text is always the final assistant turn. Tool calls
        themselves are not streamed to the client in Stage 1.
        """
        working_messages = list(messages)

        for _ in range(MAX_TOOL_ITERATIONS):
            with self._client.messages.stream(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=system_prompt,
                messages=working_messages,
                tools=TOOLS,
            ) as stream:
                for text in stream.text_stream:
                    payload = json.dumps({"type": "delta", "text": text})
                    yield f"data: {payload}\n\n".encode()
                final_message = stream.get_final_message()

            if final_message.stop_reason != "tool_use":
                break

            assistant_content = [_serialize_content_block(b) for b in final_message.content]
            working_messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in final_message.content:
                if block.type == "tool_use":
                    result_text = dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
            working_messages.append({"role": "user", "content": tool_results})
        else:
            logger.warning("Atrium exchange_stream hit MAX_TOOL_ITERATIONS without a final answer.")

        yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"


class ClaudeCodeAdapter:
    """
    Phase 2C adapter — routes through a persistent stream-json subprocess.
    Replaces the Phase 2A one-shot -p approach and the PTY/pexpect prototype.

    Yields SSE byte chunks in the same format as AtriumAnthropicAdapter:
      data: {"type": "delta",          "text": "..."}
      data: {"type": "activity",       "text": "Reading foo.md"}
      data: {"type": "context_status", "used": N, "total": N, "pct": N}
      data: {"type": "done"}
    """

    def __init__(self, session=None):
        self._session = session

    def warm(self) -> Generator[bytes, None, None]:
        """
        Ensure the stream-json subprocess is spawned. Yields SSE events:
          type: ready        — subprocess was already live (same context)
          type: reconstructed — cold spawn; history injected from DB + ApertureLog
        """
        from django.conf import settings
        from claude import service as claude_service

        if not self._session:
            return
        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        session_id = str(self._session.id)

        was_alive = claude_service.is_session_alive(session_id)

        # On cold spawn: fire idle-threshold keeper check before building context.
        if not was_alive:
            _trigger_idle_keeper_if_due(self._session)

        opening_context, provenance_note = _build_cold_spawn_context(self._session)
        claude_service.get_or_spawn(session_id, cwd, opening_context if not was_alive else None)

        pid = _pty_pid(session_id)
        if pid and self._session.pty_pid != pid:
            self._session.pty_pid = pid
            self._session.save(update_fields=["pty_pid", "updated_at"])

        if not was_alive and opening_context:
            yield b"data: " + json.dumps({
                "type": "reconstructed",
                "provenance": provenance_note,
            }).encode() + b"\n\n"
        else:
            yield b"data: " + json.dumps({"type": "ready"}).encode() + b"\n\n"

    def exchange_stream(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> Generator[bytes, None, None]:
        from django.conf import settings
        from claude import service as claude_service

        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        session_id = str(self._session.id) if self._session else "global"
        logger.info("[atrium] ClaudeCodeAdapter stream-json: session=%s cwd=%s", session_id, cwd)

        # Extract the latest user message — subprocess tracks history itself.
        user_message = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                user_message = msg["content"]
                break

        if not user_message:
            yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"
            return

        # Pass opening_context so a cold spawn triggered by exchange (not warm)
        # still gets history injected before the first real message.
        was_alive = claude_service.is_session_alive(session_id)
        opening_context, _ = _build_cold_spawn_context(self._session) if not was_alive else (None, None)

        for event_type, text in claude_service.send_to_session(
            session_id, user_message, cwd, opening_context
        ):
            if event_type == "context_status":
                payload = json.dumps({"type": "context_status", **json.loads(text)})
            elif event_type == "activity":
                payload = json.dumps({"type": "activity", "text": text})
            elif event_type == "fallback":
                payload = json.dumps({"type": "fallback"})
            else:  # delta
                payload = json.dumps({"type": "delta", "text": text})
            yield f"data: {payload}\n\n".encode()

        # Store PID after first successful exchange.
        pid = _pty_pid(session_id)
        if pid and self._session and self._session.pty_pid != pid:
            self._session.pty_pid = pid
            self._session.save(update_fields=["pty_pid", "updated_at"])

        yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"

    def compact(self, cwd: str) -> str | None:
        """Run /compact in the PTY. Returns compact summary text."""
        from claude import service as claude_service
        if not self._session:
            return None
        session_id = str(self._session.id)
        return claude_service.compact_pty(session_id, cwd)

    def reset(self, cwd: str) -> None:
        """
        Terminate the live subprocess and respawn with orientation-only context
        (compact summary + session_context; no turn history). The DB entry archive
        is preserved — only the subprocess state is cleared.
        """
        from claude import service as claude_service
        if not self._session:
            return
        session_id = str(self._session.id)
        claude_service.terminate_session(session_id)
        orientation = _build_orientation_context(self._session)
        claude_service.get_or_spawn(session_id, cwd, orientation)


class AtriumAIService:
    """
    Provider-agnostic façade for Atrium session AI exchanges.

    Usage (in a streaming view):
        ai = AtriumAIService()
        full_text = []
        for chunk in ai.exchange_stream(atrium_session, user_message):
            yield chunk
            # full_text is accumulated inside; no post-processing needed by caller
    """

    def __init__(self, session=None):
        from django.conf import settings
        use_claude_code = False

        # Per-session dispatch: sponsor slug in PUDDLEJUMP_GROUPS wins.
        if session and session.sponsor_object_id:
            try:
                sponsor_slug = getattr(session.sponsor, "slug", None)
                use_claude_code = sponsor_slug in PUDDLEJUMP_GROUPS
            except Exception:
                pass

        # Fall back to global toggle (useful for testing without a sponsor).
        if not use_claude_code:
            use_claude_code = getattr(settings, "ATRIUM_USE_CLAUDE_CODE", False)

        if use_claude_code:
            sponsor_slug = getattr(getattr(session, "sponsor", None), "slug", "global") if session else "global"
            logger.info("[atrium] AtriumAIService: ClaudeCodeAdapter PTY (sponsor=%s)", sponsor_slug)
            self._adapter = ClaudeCodeAdapter(session=session)
        else:
            self._adapter = AtriumAnthropicAdapter()

    def warm(self) -> Generator[bytes, None, None]:
        """
        Pre-warm the PTY for this session. Yields a `type: ready` SSE event.
        Only meaningful for ClaudeCodeAdapter sessions.
        """
        if hasattr(self._adapter, "warm"):
            yield from self._adapter.warm()
        else:
            yield b"data: " + json.dumps({"type": "ready"}).encode() + b"\n\n"

    def compact(self, session) -> str | None:
        """
        Run /compact in the PTY and store the summary in ApertureLog.
        Returns the summary text.
        """
        if not hasattr(self._adapter, "compact"):
            return None
        from django.conf import settings
        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        summary = self._adapter.compact(cwd)
        if summary and session.initiative_id:
            _store_compact_summary(session, summary)
        return summary

    def reset(self, session) -> None:
        """
        Terminate subprocess and respawn with orientation-only context.
        No-op for non-ClaudeCode adapters.
        """
        if not hasattr(self._adapter, "reset"):
            return
        from django.conf import settings
        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        self._adapter.reset(cwd)

    def exchange_stream(
        self,
        session,
        user_message: str,
    ) -> Generator[bytes, None, None]:
        """
        Builds the system prompt from session_context, constructs the message
        history from existing AtriumSessionEntry records, then streams the
        Claude API response.

        Saves the user entry before streaming and the assistant entry after.
        Yields SSE byte chunks for StreamingHttpResponse.
        """
        from django.utils import timezone
        from atrium.models import AtriumSessionEntry, AtriumSessionRole

        # Save user entry
        AtriumSessionEntry.objects.create(
            session=session,
            role=AtriumSessionRole.USER,
            content=user_message,
        )

        system_prompt = _build_system_prompt(session)
        messages = _session_to_messages(session)

        full_response: list[str] = []

        for chunk in self._adapter.exchange_stream(system_prompt, messages):
            try:
                decoded = chunk.decode()
                if decoded.startswith("data: "):
                    payload = json.loads(decoded[6:])
                    if payload.get("type") == "delta":
                        full_response.append(payload.get("text", ""))
            except Exception:
                pass
            yield chunk

        # Save assistant entry
        assistant_text = "".join(full_response)
        if assistant_text:
            AtriumSessionEntry.objects.create(
                session=session,
                role=AtriumSessionRole.ASSISTANT,
                content=assistant_text,
            )

        # Update session activity timestamp
        session.last_activity_at = timezone.now()
        session.save(update_fields=["last_activity_at", "updated_at"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_system_prompt(session) -> str:
    from atrium.ai.context import BerylPersonalContextBuilder

    parts = [
        "You are an AI thinking partner for a member working inside Mixtape — "
        "a collaborative platform for creative and professional work. "
        "You help the member think clearly, plan effectively, and make good decisions. "
        "Be direct and specific. Match the depth of the question.",
    ]

    if session.sponsor_object_id:
        sponsor = session.sponsor
        if sponsor is not None:
            sponsor_slug = getattr(sponsor, "slug", None)
            sponsor_title = getattr(sponsor, "title", None) or getattr(sponsor, "username", str(sponsor))
            sponsor_summary = getattr(sponsor, "summary", "") or ""
            sponsor_type = session.sponsor_content_type.model if session.sponsor_content_type_id else "unknown"
            sponsor_line = f"{sponsor_type.capitalize()}: {sponsor_title}"
            if sponsor_slug:
                sponsor_line += f" (slug: {sponsor_slug})"
            if sponsor_summary:
                sponsor_line += f" — {sponsor_summary.strip()}"
            parts.append(f"\n\nSponsor context:\n{sponsor_line}")
            if sponsor_slug in PUDDLEJUMP_GROUPS:
                parts.append(
                    "This session operates in the Puddlejump planning context for this group. "
                    "You have access to the group's canon documents, ADRs, and decision records."
                )

    if session.session_context and session.session_context.strip():
        parts.append(f"\n\nSession context:\n{session.session_context.strip()}")

    personal_ctx = BerylPersonalContextBuilder().build(session)
    if personal_ctx:
        parts.append(f"\n\nPersonal context:\n{personal_ctx}")

    return "\n".join(parts)


def _serialize_content_block(block) -> dict:
    """Serialize an Anthropic content block to the wire format the API accepts.

    block.model_dump() includes SDK-internal fields (e.g. parsed_output) that
    the API rejects when the block is sent back as part of conversation history.
    """
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    return {"type": block.type}


def _build_claude_code_prompt(system_prompt: str, messages: list[dict]) -> str:
    """
    Flatten system prompt + conversation history into a single stdin prompt
    for the claude -p subprocess. Claude Code CLI is single-turn; we carry
    the full history so the session feels continuous.
    """
    parts = [system_prompt.strip(), ""]
    for msg in messages:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{role_label}: {msg['content'].strip()}")
    parts.append("")
    parts.append("Respond directly.")
    return "\n".join(parts)


def _session_to_messages(session) -> list[dict]:
    """
    Convert existing AtriumSessionEntry records (in order) to Anthropic
    messages format. The most-recently-saved user entry is already in DB
    so it will be included here.
    """
    entries = list(session.entries.order_by("created_at"))
    messages = []
    for entry in entries:
        role = "user" if entry.role == "user" else "assistant"
        messages.append({"role": role, "content": entry.content})

    # Anthropic requires starting with a user turn and alternating roles.
    # Collapse consecutive same-role turns.
    if messages and messages[0]["role"] != "user":
        messages = messages[1:]

    collapsed = []
    for msg in messages:
        if collapsed and collapsed[-1]["role"] == msg["role"]:
            collapsed[-1]["content"] += "\n\n" + msg["content"]
        else:
            collapsed.append(dict(msg))
    return collapsed


# ---------------------------------------------------------------------------
# Session / Initiative resolution helpers
# ---------------------------------------------------------------------------

# How many recent turns to inject on cold spawn (token-bounded below).
_HISTORY_INJECT_TURNS = 10
# Approximate token budget for injected history (tokens ≈ chars / 4).
_HISTORY_INJECT_MAX_CHARS = 16_000  # ~4 000 tokens

# Idle-threshold in minutes per cadence setting.
_IDLE_THRESHOLDS = {"light": None, "steady": 30, "active": 10}
# Turn-count thresholds per cadence setting (count of *assistant* entries).
_TURN_THRESHOLDS = {"light": None, "steady": 8, "active": 4}


def _pty_pid(session_id: str) -> int | None:
    from claude import service as claude_service
    proc = claude_service._session_registry.get(session_id)
    if proc is None:
        return None
    try:
        return proc.pid
    except Exception:
        return None


def _resolve_aperture_log(session):
    """
    Navigate from AtriumSession → Initiative → ApertureLog.

    AtriumSession has a polymorphic sponsor GFK (Group or UserProfile).
    The matching Initiative is the one whose sponsor GFK points to the same object.
    Falls back to the member's personal Initiative when no sponsor is set.
    Returns (ApertureLog, cadence) or (None, "steady").
    """
    if session is None:
        return None, "steady"
    try:
        from initiatives.models import ApertureLog, Initiative

        if session.sponsor_content_type_id and session.sponsor_object_id:
            initiative = Initiative.objects.filter(
                sponsor_content_type_id=session.sponsor_content_type_id,
                sponsor_object_id=session.sponsor_object_id,
                deleted_at__isnull=True,
            ).first()
        else:
            # Personal session — find the member's personal Initiative.
            from django.contrib.contenttypes.models import ContentType
            member = session.member
            ct = ContentType.objects.get_for_model(member)
            initiative = Initiative.objects.filter(
                sponsor_content_type=ct,
                sponsor_object_id=member.pk,
                is_personal=True,
                deleted_at__isnull=True,
            ).first()

        if initiative is None:
            return None, "steady"

        log = ApertureLog.objects.filter(initiative=initiative).first()
        cadence = getattr(log, "compact_cadence", "steady") if log else "steady"
        return log, cadence

    except Exception as exc:
        logger.warning("[atrium] _resolve_aperture_log failed: %s", exc)
        return None, "steady"


def _build_orientation_context(session) -> str | None:
    """
    Build the orientation context string for a session reset.
    Injects compact summary and session_context only — no turn history.
    """
    if session is None:
        return None
    try:
        parts = []
        log, _ = _resolve_aperture_log(session)
        if log and log.compact_summary:
            ts = log.compact_at.strftime("%Y-%m-%d") if log.compact_at else "prior"
            parts.append(
                f"[Compact summary — distilled {ts}]\n"
                f"{log.compact_summary.strip()}\n"
                f"[End compact summary]"
            )
        if session.session_context and session.session_context.strip():
            parts.append(
                f"[Session context]\n"
                f"{session.session_context.strip()}\n"
                f"[End session context]"
            )
        if not parts:
            return None
        return (
            "[Session reset — starting fresh. The following is orientation context "
            "for this new thread. No prior conversation history is available.]\n\n"
            + "\n\n".join(parts)
        )
    except Exception as exc:
        logger.warning("[atrium] _build_orientation_context failed: %s", exc)
        return None


def _build_cold_spawn_context(session) -> tuple[str | None, str | None]:
    """
    Build the opening context string to inject when a cold spawn occurs.

    Returns (context_str, provenance_note):
      context_str    — formatted string to send as the first subprocess message
      provenance_note — human-readable summary of what was injected (for UI badge)
    """
    if session is None:
        return None, None

    try:
        from atrium.models import AtriumSessionEntry, AtriumSessionRole

        log, _ = _resolve_aperture_log(session)

        parts = []
        provenance_parts = []

        # --- compact summary block ---
        if log and log.compact_summary:
            ts = log.compact_at.strftime("%Y-%m-%d") if log.compact_at else "prior"
            parts.append(
                f"[Compact summary — distilled {ts}]\n"
                f"{log.compact_summary.strip()}\n"
                f"[End compact summary]"
            )
            provenance_parts.append(f"compact summary ({ts})")

        # --- recent turn history ---
        entries = list(
            AtriumSessionEntry.objects.filter(session=session)
            .order_by("-created_at")[: _HISTORY_INJECT_TURNS * 2]
        )
        entries.reverse()  # oldest first

        if entries:
            turn_lines = []
            char_budget = _HISTORY_INJECT_MAX_CHARS
            for entry in entries:
                role_label = "User" if entry.role == AtriumSessionRole.USER else "Assistant"
                line = f"{role_label}: {entry.content.strip()}"
                if len(line) > char_budget:
                    break
                turn_lines.append(line)
                char_budget -= len(line)

            if turn_lines:
                n = len([l for l in turn_lines if l.startswith("User:")])
                parts.append(
                    f"[Recent conversation — last {n} exchange(s)]\n"
                    + "\n".join(turn_lines)
                    + "\n[End recent conversation — continue from here]"
                )
                provenance_parts.append(f"last {n} turn(s)")

        if not parts:
            return None, None

        context_str = "\n\n".join(parts)
        provenance_note = "Resumed from " + " + ".join(provenance_parts) + "."
        return context_str, provenance_note

    except Exception as exc:
        logger.warning("[atrium] _build_cold_spawn_context failed: %s", exc)
        return None, None


def _get_compact_summary(session) -> str | None:
    """Return the ApertureLog compact summary for injection (legacy single-field path)."""
    context, _ = _build_cold_spawn_context(session)
    return context


def _store_compact_summary(session, summary: str) -> None:
    """Store compact summary in the session's ApertureLog."""
    try:
        from django.utils import timezone
        log, _ = _resolve_aperture_log(session)
        if log is None:
            return
        log.compact_summary = summary
        log.compact_at = timezone.now()
        log.save(update_fields=["compact_summary", "compact_at"])
    except Exception as exc:
        logger.warning("[atrium] _store_compact_summary failed: %s", exc)


def _trigger_keeper_if_due(session) -> None:
    """
    Fire the Continuous Keeper task if the turn threshold for this session's
    cadence has been reached. Called from the AtriumSessionEntry post_save signal.
    """
    try:
        log, cadence = _resolve_aperture_log(session)
        threshold = _TURN_THRESHOLDS.get(cadence)
        if threshold is None:
            return  # "light" cadence — no turn-count trigger

        from atrium.models import AtriumSessionEntry, AtriumSessionRole
        since = getattr(log, "compact_at", None)
        qs = AtriumSessionEntry.objects.filter(
            session=session,
            role=AtriumSessionRole.ASSISTANT,
        )
        if since:
            qs = qs.filter(created_at__gt=since)
        count = qs.count()
        if count >= threshold:
            from atrium.tasks import keeper_compact_task
            keeper_compact_task.delay(str(session.id))
    except Exception as exc:
        logger.warning("[atrium] _trigger_keeper_if_due failed: %s", exc)


def _trigger_idle_keeper_if_due(session) -> None:
    """
    Fire the Continuous Keeper task if the session has been idle past the
    cadence threshold. Called at the start of warm() on cold spawn.
    """
    try:
        from django.utils import timezone
        log, cadence = _resolve_aperture_log(session)
        idle_minutes = _IDLE_THRESHOLDS.get(cadence)
        if idle_minutes is None:
            return  # "light" cadence — no idle trigger

        last_end = getattr(log, "last_session_end", None)
        last_compact = getattr(log, "compact_at", None)
        if last_end is None:
            return

        idle_delta = (timezone.now() - last_end).total_seconds() / 60
        if idle_delta >= idle_minutes:
            # Only re-compact if compact is stale (older than last_end).
            if last_compact is None or last_compact < last_end:
                from atrium.tasks import keeper_compact_task
                keeper_compact_task.delay(str(session.id))
    except Exception as exc:
        logger.warning("[atrium] _trigger_idle_keeper_if_due failed: %s", exc)
