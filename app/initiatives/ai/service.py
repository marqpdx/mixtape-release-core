# initiatives/ai/service.py
#
# Provider-agnostic AI service for Initiatives.
#
# Architecture:
#   InitiativeAIService  — public API; delegates to an adapter
#   AnthropicAdapter     — Anthropic Claude implementation (v0 default)
#
# To add a new provider:
#   1. Implement the same interface as AnthropicAdapter
#   2. Change _get_adapter() or inject via settings (AI_PROVIDER)
#
# SSE streaming:
#   exchange_stream() yields raw SSE-formatted byte strings.
#   The Django view wraps this in a StreamingHttpResponse with
#   content_type="text/event-stream".

import json
import logging
import os
from typing import Generator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adapter interface (duck-typed — no ABC to keep it light)
# ---------------------------------------------------------------------------

class AnthropicAdapter:
    """
    Wraps the Anthropic Messages API.

    Uses the synchronous client for Celery tasks and a streaming client
    for SSE views.  Provider-agnostic callers go through InitiativeAIService.
    """

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 2048

    def __init__(self):
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Exchange (SSE streaming)
    # ------------------------------------------------------------------

    def exchange_stream(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> Generator[bytes, None, None]:
        """
        Yields SSE-formatted byte chunks:
          data: {"type": "delta", "text": "..."}\n\n
          data: {"type": "done"}\n\n
        """
        with self._client.messages.stream(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                payload = json.dumps({"type": "delta", "text": text})
                yield f"data: {payload}\n\n".encode()
            yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"

    # ------------------------------------------------------------------
    # Distillation (sync)
    # ------------------------------------------------------------------

    def propose_distillation(
        self,
        initiative_title: str,
        initiative_direction: str,
        transcript: list[dict],
    ) -> dict:
        """
        Returns a distillation dict with keys:
          decisions, open_questions, actions, notes
        """
        system = (
            "You are a structured note-taker helping a team capture durable knowledge "
            "from a working session. Given a session transcript, extract:\n"
            "- decisions: list of concrete decisions made\n"
            "- open_questions: list of unresolved questions\n"
            "- actions: list of next actions\n"
            "- notes: any additional context worth preserving\n\n"
            "Return ONLY valid JSON with these four keys. "
            "Each value is a list of concise strings (empty list if none)."
        )
        human_msg = (
            f"Initiative: {initiative_title}\n"
            f"Direction: {initiative_direction or 'Not specified'}\n\n"
            "Transcript:\n"
            + _format_transcript(transcript)
        )
        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": human_msg}],
        )
        raw = response.content[0].text.strip()
        try:
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("distillation_json_parse_failed raw=%r", raw[:200])
            return {
                "decisions": [],
                "open_questions": [],
                "actions": [],
                "notes": raw,
            }

    # ------------------------------------------------------------------
    # Rolling summary update (sync)
    # ------------------------------------------------------------------

    def update_rolling_summary(
        self,
        initiative_title: str,
        prior_summary: dict,
        distillation: dict,
    ) -> dict:
        """
        Returns an updated rolling summary dict with keys:
          current_direction, key_decisions, open_questions, where_we_are_now
        """
        system = (
            "You maintain a living rolling summary for an ongoing team initiative. "
            "Given the prior summary and new session distillation, produce an updated summary.\n\n"
            "Return ONLY valid JSON with exactly these four keys:\n"
            "- current_direction: one sentence describing where the initiative is headed\n"
            "- key_decisions: list of the most important decisions made across all sessions\n"
            "- open_questions: list of currently unresolved questions\n"
            "- where_we_are_now: one paragraph describing current state\n\n"
            "Merge, deduplicate, and synthesise. Do not grow lists unboundedly — remove resolved items."
        )
        human_msg = (
            f"Initiative: {initiative_title}\n\n"
            f"Prior summary:\n{json.dumps(prior_summary, indent=2)}\n\n"
            f"New distillation from completed session:\n{json.dumps(distillation, indent=2)}"
        )
        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": human_msg}],
        )
        raw = response.content[0].text.strip()
        try:
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("rolling_summary_json_parse_failed raw=%r", raw[:200])
            return prior_summary  # Fall back to prior on parse failure

    # ------------------------------------------------------------------
    # Quality scan (sync)
    # ------------------------------------------------------------------

    def quality_scan(self, title: str, body: str) -> dict:
        """
        Returns {"assessment": "ok" | "advisory", "note": str}.
        """
        system = (
            "You review knowledge artifacts for quality. Assess whether this artifact:\n"
            "1. Says something concrete and specific (not just platitudes)\n"
            "2. Is self-contained enough to be useful out of context\n"
            "3. Doesn't just repeat the title in the body\n\n"
            'Return ONLY valid JSON: {"assessment": "ok" | "advisory", "note": "..."}. '
            '"advisory" means the artifact needs improvement; "ok" means it is solid.'
        )
        human_msg = f"Title: {title}\n\nBody:\n{body}"
        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": human_msg}],
        )
        raw = response.content[0].text.strip()
        try:
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"assessment": "ok", "note": ""}


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class InitiativeAIService:
    """
    Provider-agnostic façade.  All callers in views/tasks use this class.

    Usage:
        ai = InitiativeAIService()
        # Sync:
        result = ai.propose_distillation(initiative, session)
        # Streaming generator (for SSE views):
        for chunk in ai.exchange_stream(initiative, session, message, username):
            yield chunk
    """

    def __init__(self):
        self._adapter = self._get_adapter()

    def _get_adapter(self):
        provider = os.getenv("AI_PROVIDER", "anthropic").lower()
        if provider == "anthropic":
            return AnthropicAdapter()
        raise NotImplementedError(f"AI_PROVIDER={provider!r} not supported yet.")

    # ------------------------------------------------------------------
    # SSE exchange stream
    # ------------------------------------------------------------------

    def exchange_stream(
        self,
        initiative,
        session,
        user_message: str,
        username: str,
    ) -> Generator[bytes, None, None]:
        """
        Appends the user turn to session.raw_transcript, then streams the
        AI response.  Appends the completed assistant turn on stream end.

        Yields SSE byte chunks.  Caller wraps in StreamingHttpResponse.
        """
        # Append user turn
        session.append_turn(speaker="human", text=user_message, username=username)

        system_prompt = _build_exchange_system_prompt(initiative)
        messages = _transcript_to_messages(session.raw_transcript)

        full_response = []

        for chunk in self._adapter.exchange_stream(system_prompt, messages):
            # Collect the text to build the assistant turn
            try:
                decoded = chunk.decode()
                if decoded.startswith("data: "):
                    payload = json.loads(decoded[6:])
                    if payload.get("type") == "delta":
                        full_response.append(payload.get("text", ""))
            except Exception:
                pass
            yield chunk

        # Append completed assistant turn to transcript
        assistant_text = "".join(full_response)
        if assistant_text:
            session.append_turn(speaker="assistant", text=assistant_text, username=None)

    # ------------------------------------------------------------------
    # Distillation
    # ------------------------------------------------------------------

    def propose_distillation(self, initiative, session) -> dict:
        return self._adapter.propose_distillation(
            initiative_title=initiative.title,
            initiative_direction=initiative.direction or "",
            transcript=session.raw_transcript or [],
        )

    # ------------------------------------------------------------------
    # Rolling summary
    # ------------------------------------------------------------------

    def update_rolling_summary(self, initiative, session) -> dict:
        return self._adapter.update_rolling_summary(
            initiative_title=initiative.title,
            prior_summary=initiative.rolling_summary_display,
            distillation=session.distillation or {},
        )

    # ------------------------------------------------------------------
    # Quality scan
    # ------------------------------------------------------------------

    def quality_scan(self, artifact) -> dict:
        return self._adapter.quality_scan(
            title=artifact.title or "",
            body=artifact.body or "",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_exchange_system_prompt(initiative) -> str:
    summary = initiative.rolling_summary_display
    parts = [
        "You are an AI collaborator working inside an Initiative — a structured inquiry session "
        "for a team working through a complex question or project.",
        f"\nInitiative: {initiative.title}",
    ]
    if initiative.direction:
        parts.append(f"Direction: {initiative.direction}")
    if summary.get("current_direction"):
        parts.append(f"Current direction: {summary['current_direction']}")
    if summary.get("where_we_are_now"):
        parts.append(f"Where we are now: {summary['where_we_are_now']}")
    if summary.get("key_decisions"):
        parts.append("Key decisions so far:\n" + "\n".join(f"- {d}" for d in summary["key_decisions"]))
    if summary.get("open_questions"):
        parts.append("Open questions:\n" + "\n".join(f"- {q}" for q in summary["open_questions"]))
    parts.append(
        "\nBe concise, direct, and focused on the initiative's goals. "
        "Help the team think clearly, not just agree with them."
    )
    return "\n".join(parts)


def _transcript_to_messages(transcript: list) -> list[dict]:
    """Convert raw_transcript turns to Anthropic messages format."""
    messages = []
    for turn in transcript:
        role = "user" if turn.get("speaker") == "human" else "assistant"
        text = turn.get("text", "")
        if text:
            messages.append({"role": role, "content": text})
    # Ensure we start with a user message (Anthropic requirement)
    if messages and messages[0]["role"] != "user":
        messages = messages[1:]
    # Ensure alternating turns — collapse consecutive same-role turns
    collapsed = []
    for msg in messages:
        if collapsed and collapsed[-1]["role"] == msg["role"]:
            collapsed[-1]["content"] += "\n\n" + msg["content"]
        else:
            collapsed.append(dict(msg))
    return collapsed


def _format_transcript(transcript: list) -> str:
    lines = []
    for turn in transcript:
        speaker = turn.get("username") or turn.get("speaker", "?")
        lines.append(f"{speaker}: {turn.get('text', '')}")
    return "\n".join(lines) if lines else "(empty)"
