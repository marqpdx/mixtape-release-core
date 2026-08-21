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
    Phase 2A adapter — routes through ClaudeSubprocessService.stream()
    (local claude -p subprocess) instead of the Anthropic SDK.

    Yields the same SSE byte format as AtriumAnthropicAdapter so
    AtriumAIService.exchange_stream() needs no changes.
    """

    def exchange_stream(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> Generator[bytes, None, None]:
        from django.conf import settings
        from claude import service as claude_service

        cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()
        prompt = _build_claude_code_prompt(system_prompt, messages)
        logger.info("[atrium] ClaudeCodeAdapter: cwd=%s", cwd)

        for line in claude_service.stream(prompt, cwd=cwd):
            if line:
                payload = json.dumps({"type": "delta", "text": line})
                yield f"data: {payload}\n\n".encode()

        yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"


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

    def __init__(self):
        from django.conf import settings
        if getattr(settings, "ATRIUM_USE_CLAUDE_CODE", False):
            logger.info("[atrium] AtriumAIService: using ClaudeCodeAdapter (Phase 2A)")
            self._adapter = ClaudeCodeAdapter()
        else:
            self._adapter = AtriumAnthropicAdapter()

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
