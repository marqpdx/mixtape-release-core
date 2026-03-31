# initiatives/importers/chatgpt_parser.py
#
# Parses ChatGPT web chat export JSON.
#
# Expected shape (chatgpt.com → Settings → Data Controls → Export Data
#                 → unzip → conversations.json):
#
# [
#   {
#     "title": "Conversation title",
#     "create_time": 1700000000.0,
#     "update_time": 1700000000.0,
#     "current_node": "<last-node-id>",
#     "conversation_id": "<uuid>",
#     "mapping": {
#       "<node-id>": {
#         "id": "<node-id>",
#         "parent": "<parent-node-id>" | null,
#         "children": ["<child-node-id>"],
#         "message": {
#           "id": "<msg-id>",
#           "author": { "role": "user" | "assistant" | "system" | "tool" },
#           "create_time": 1700000000.0,
#           "content": {
#             "content_type": "text",
#             "parts": ["message text here"]
#           }
#         } | null
#       }
#     }
#   }
# ]
#
# The mapping is a tree, not a flat array. Walk from root to current_node
# using parent links to get the canonical conversation path.

import logging
from datetime import datetime, timezone

from .artifact_detector import detect_artifacts
from .base import ImportParseError, ParsedImport, ParsedTurn

logger = logging.getLogger(__name__)

INCLUDED_ROLES = {"user", "assistant"}


def parse(data: list | dict) -> ParsedImport:
    """
    Parse a ChatGPT web export.
    `data` is the already-decoded JSON (list or single object).

    Returns a ParsedImport.
    Raises ImportParseError if the data doesn't look like a ChatGPT export.
    """
    conversations = _extract_conversations(data)
    conv = conversations[0]

    title = conv.get("title") or "Imported ChatGPT Conversation"
    mapping = conv.get("mapping") or {}
    current_node = conv.get("current_node")

    if not mapping:
        raise ImportParseError("No message mapping found in ChatGPT export.")

    # Walk the tree from current_node back to root, then reverse for chronological order
    path = _walk_to_root(mapping, current_node)
    path.reverse()  # root → current

    turns: list[ParsedTurn] = []
    for node_id in path:
        node = mapping.get(node_id, {})
        msg = node.get("message")
        if not msg:
            continue

        role = (msg.get("author") or {}).get("role") or ""
        if role not in INCLUDED_ROLES:
            continue

        text = _extract_text(msg)
        if not text:
            continue

        speaker = "human" if role == "user" else "assistant"
        timestamp = _unix_to_iso(msg.get("create_time"))

        turns.append(ParsedTurn(
            speaker=speaker,
            text=text,
            timestamp=timestamp,
            username=None,
        ))

    if not turns:
        raise ImportParseError("No user/assistant messages found in this ChatGPT export.")

    turn_dicts = [t.to_dict() for t in turns]
    detected = detect_artifacts(turn_dicts)

    word_count = sum(len((t.text or "").split()) for t in turns)
    human_turns = sum(1 for t in turns if t.speaker == "human")
    assistant_turns = sum(1 for t in turns if t.speaker == "assistant")

    return ParsedImport(
        source_format="chatgpt",
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


def looks_like_chatgpt_export(data: list | dict) -> bool:
    """Heuristic: does this JSON look like a ChatGPT export?"""
    try:
        convs = _extract_conversations(data)
        first = convs[0]
        return "mapping" in first and "current_node" in first
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_conversations(data: list | dict) -> list[dict]:
    if isinstance(data, dict):
        if "mapping" in data and "current_node" in data:
            return [data]
        raise ImportParseError("Unrecognised ChatGPT export shape.")

    if isinstance(data, list):
        if not data:
            raise ImportParseError("Empty array in ChatGPT export.")
        if isinstance(data[0], dict):
            return data
        raise ImportParseError("Expected list of conversation objects.")

    raise ImportParseError(f"Unexpected top-level type: {type(data).__name__}")


def _walk_to_root(mapping: dict, start_id: str | None) -> list[str]:
    """
    Walk from start_id back to the root following parent links.
    Returns the list of node IDs in root→start order (before reversing).
    """
    if not start_id:
        return list(mapping.keys())

    path = []
    current = start_id
    visited: set[str] = set()

    while current and current not in visited:
        visited.add(current)
        path.append(current)
        node = mapping.get(current, {})
        parent = node.get("parent")
        if not parent or parent not in mapping:
            break
        current = parent

    return path


def _extract_text(msg: dict) -> str:
    content = msg.get("content") or {}
    parts = content.get("parts") or []
    pieces = []
    for part in parts:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, dict):
            # Some parts are structured (e.g. multimodal); extract text field
            pieces.append(part.get("text") or "")
    return "\n".join(p for p in pieces if p).strip()


def _unix_to_iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None
