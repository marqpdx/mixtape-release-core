# initiatives/importers/claude_parser.py
#
# Parses Claude web chat export JSON.
#
# Expected shape (claude.ai → Settings → Export Data → conversations.json):
#
# [
#   {
#     "uuid": "...",
#     "name": "Conversation title",
#     "created_at": "2024-01-01T00:00:00.000Z",
#     "updated_at": "...",
#     "chat_messages": [
#       {
#         "uuid": "...",
#         "sender": "human" | "assistant",
#         "text": "...",
#         "created_at": "...",
#         "attachments": [],
#         "files": []
#       }
#     ]
#   }
# ]
#
# The file may contain a single conversation or an array of conversations.
# If multiple, we parse the first one (the UI will offer multi-conv selection
# in a future pass; for now the user exports the conversation they want).

import logging

from .artifact_detector import detect_artifacts
from .base import ImportParseError, ParsedImport, ParsedTurn

logger = logging.getLogger(__name__)

SENDER_MAP = {
    "human": "human",
    "user": "human",
    "assistant": "assistant",
    "claude": "assistant",
}


def parse(data: list | dict) -> ParsedImport:
    """
    Parse a Claude web export.
    `data` is the already-decoded JSON (list or single object).

    Returns a ParsedImport.
    Raises ImportParseError if the data doesn't look like a Claude export.
    """
    conversations = _extract_conversations(data)

    # Take the first conversation for now
    conv = conversations[0]

    messages = conv.get("chat_messages") or conv.get("messages") or []
    if not isinstance(messages, list):
        raise ImportParseError("chat_messages is not a list.")

    title = conv.get("name") or conv.get("title") or "Imported Claude Conversation"

    turns: list[ParsedTurn] = []
    for msg in messages:
        sender_raw = msg.get("sender") or msg.get("role") or ""
        speaker = SENDER_MAP.get(sender_raw.lower(), "human")

        text = _extract_text(msg)
        if not text:
            continue

        turns.append(ParsedTurn(
            speaker=speaker,
            text=text,
            timestamp=msg.get("created_at"),
            username=None,
        ))

    if not turns:
        raise ImportParseError("No messages found in this Claude export.")

    turn_dicts = [t.to_dict() for t in turns]
    detected = detect_artifacts(turn_dicts)

    word_count = sum(len((t.text or "").split()) for t in turns)
    human_turns = sum(1 for t in turns if t.speaker == "human")
    assistant_turns = sum(1 for t in turns if t.speaker == "assistant")

    return ParsedImport(
        source_format="claude",
        conversation_title=title,
        turns=turns,
        detected_artifacts=detected,
        stats={
            "turn_count": len(turns),
            "human_turns": human_turns,
            "assistant_turns": assistant_turns,
            "word_count": word_count,
            "conversation_count": len(conversations),
        },
    )


def looks_like_claude_export(data: list | dict) -> bool:
    """Heuristic: does this JSON look like a Claude export?"""
    try:
        convs = _extract_conversations(data)
        first = convs[0]
        return "chat_messages" in first or (
            "messages" in first and any(
                m.get("sender") in ("human", "assistant")
                for m in first.get("messages", [])[:3]
            )
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_conversations(data: list | dict) -> list[dict]:
    if isinstance(data, dict):
        # Single conversation object
        if "chat_messages" in data or "messages" in data:
            return [data]
        raise ImportParseError("Unrecognised Claude export shape (dict without chat_messages).")

    if isinstance(data, list):
        if not data:
            raise ImportParseError("Empty array in Claude export.")
        if isinstance(data[0], dict):
            return data
        raise ImportParseError("Expected list of conversation objects.")

    raise ImportParseError(f"Unexpected top-level type: {type(data).__name__}")


def _extract_text(msg: dict) -> str:
    """Extract plain text from a message object."""
    # Standard field
    text = msg.get("text") or msg.get("content") or ""
    if isinstance(text, list):
        # Some versions nest content as [{type: "text", text: "..."}]
        parts = []
        for block in text:
            if isinstance(block, dict):
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        text = "\n".join(p for p in parts if p)
    return (text or "").strip()
