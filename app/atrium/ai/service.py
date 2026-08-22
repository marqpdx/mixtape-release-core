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
    Phase 2C adapter — routes through a persistent PTY-based interactive
    claude session. Replaces the Phase 2A -p subprocess approach.

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
        Ensure the PTY is spawned. Yields a `type: ready` event when warm.
        """
        from django.conf import settings
        from claude import service as claude_service

        if not self._session:
            return
        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        session_id = str(self._session.id)
        opening_context = _get_compact_summary(self._session)
        claude_service.get_or_spawn(session_id, cwd, opening_context)
        pid = _pty_pid(session_id)
        if pid and self._session.pty_pid != pid:
            self._session.pty_pid = pid
            self._session.save(update_fields=["pty_pid", "updated_at"])
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
        opening_context = _get_compact_summary(self._session)
        logger.info("[atrium] ClaudeCodeAdapter PTY: session=%s cwd=%s", session_id, cwd)

        # Extract the latest user message — the PTY tracks history itself.
        user_message = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                user_message = msg["content"]
                break

        if not user_message:
            yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"
            return

        for event_type, text in claude_service.send_to_pty(session_id, user_message, cwd):
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
# PTY helpers
# ---------------------------------------------------------------------------

def _pty_pid(session_id: str) -> int | None:
    from claude import service as claude_service
    proc = claude_service._pty_registry.get(session_id)
    if proc is None:
        return None
    try:
        return proc.pid
    except Exception:
        return None


def _get_compact_summary(session) -> str | None:
    """Return the ApertureLog compact summary for a session's initiative, if any."""
    if session is None:
        return None
    try:
        initiative_id = getattr(session, "initiative_id", None)
        if initiative_id is None:
            return None
        from initiatives.models import ApertureLog
        log = ApertureLog.objects.filter(initiative_id=initiative_id).first()
        if log and log.compact_summary:
            ts = log.compact_at.strftime("%Y-%m-%d") if log.compact_at else "prior"
            return (
                f"[Prior session summary — compacted {ts}]\n"
                f"{log.compact_summary}\n"
                f"[End prior context]"
            )
    except Exception:
        pass
    return None


def _store_compact_summary(session, summary: str) -> None:
    """Store compact summary in the session's ApertureLog."""
    try:
        from django.utils import timezone
        from initiatives.models import ApertureLog
        initiative_id = getattr(session, "initiative_id", None)
        if initiative_id is None:
            return
        ApertureLog.objects.filter(initiative_id=initiative_id).update(
            compact_summary=summary,
            compact_at=timezone.now(),
        )
    except Exception as exc:
        logger.warning("[atrium] _store_compact_summary failed: %s", exc)
