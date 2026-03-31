# initiatives/importers/freeform_parser.py
#
# Handles freeform JSON that doesn't match Claude or ChatGPT shapes.
# Also serves as the auto-dispatch entry point: detect format first,
# fall back to freeform parsing if neither known format matches.
#
# Freeform formats we attempt to handle:
#   1. Array of {role, content} objects (OpenAI API-style)
#   2. Array of {speaker, text} objects (generic transcript)
#   3. Array of strings (plain turns, alternating user/assistant assumed)
#   4. Single object with a "messages" or "turns" key pointing to the above

import logging

from .artifact_detector import detect_artifacts
from .base import ImportParseError, ParsedImport, ParsedTurn

logger = logging.getLogger(__name__)

ROLE_MAP = {
    "user": "human",
    "human": "human",
    "assistant": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "claude": "assistant",
    "gpt": "assistant",
}


def parse(data: list | dict, title: str = "") -> ParsedImport:
    """
    Parse freeform JSON into a ParsedImport.
    Raises ImportParseError if we can't extract any turns.
    """
    messages = _extract_messages(data)
    if not messages:
        raise ImportParseError("Could not find any messages in this JSON file.")

    turns: list[ParsedTurn] = []
    for idx, msg in enumerate(messages):
        turn = _to_turn(msg, idx)
        if turn and turn.text:
            turns.append(turn)

    if not turns:
        raise ImportParseError("No readable turns found in this JSON file.")

    conv_title = title or _extract_title(data) or "Imported Conversation"

    turn_dicts = [t.to_dict() for t in turns]
    detected = detect_artifacts(turn_dicts)

    word_count = sum(len((t.text or "").split()) for t in turns)

    return ParsedImport(
        source_format="freeform",
        conversation_title=conv_title,
        turns=turns,
        detected_artifacts=detected,
        stats={
            "turn_count": len(turns),
            "word_count": word_count,
        },
    )


# ---------------------------------------------------------------------------
# Auto-dispatch
# ---------------------------------------------------------------------------

def auto_parse(data: list | dict) -> ParsedImport:
    """
    Try Claude parser → ChatGPT parser → freeform parser, in that order.
    Returns the first successful parse.
    """
    from . import claude_parser, chatgpt_parser

    if claude_parser.looks_like_claude_export(data):
        try:
            return claude_parser.parse(data)
        except ImportParseError:
            pass

    if chatgpt_parser.looks_like_chatgpt_export(data):
        try:
            return chatgpt_parser.parse(data)
        except ImportParseError:
            pass

    return parse(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_messages(data: list | dict) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "turns", "conversation", "chat_messages", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


def _to_turn(msg, idx: int) -> ParsedTurn | None:
    if isinstance(msg, str):
        # Plain string — alternate human/assistant
        speaker = "human" if idx % 2 == 0 else "assistant"
        return ParsedTurn(speaker=speaker, text=msg.strip())

    if not isinstance(msg, dict):
        return None

    # Extract role
    role_raw = msg.get("role") or msg.get("speaker") or msg.get("from") or ""
    speaker = ROLE_MAP.get(str(role_raw).lower(), "human")

    # Extract text
    content = msg.get("content") or msg.get("text") or msg.get("message") or ""
    if isinstance(content, list):
        # OpenAI API multi-part content
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        content = "\n".join(p for p in parts if p)

    text = (content or "").strip()
    if not text:
        return None

    return ParsedTurn(
        speaker=speaker,
        text=text,
        timestamp=msg.get("timestamp") or msg.get("created_at") or msg.get("time"),
        username=msg.get("username") or msg.get("name"),
    )


def _extract_title(data: list | dict) -> str:
    if isinstance(data, dict):
        return (
            data.get("title")
            or data.get("name")
            or data.get("subject")
            or ""
        )
    return ""
