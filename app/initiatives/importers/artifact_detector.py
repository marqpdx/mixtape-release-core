# initiatives/importers/artifact_detector.py
#
# Heuristic artifact detection from parsed turns.
# Used in the preview stage — no AI call required.
#
# Detects:
#   decision   — "we decided", "going with", "decided to", "the decision is", "settled on"
#   question   — open questions (sentences ending "?") in assistant turns
#   action     — "TODO", "next step", "action item", numbered action lists in assistant turns
#   annotation — notable insight paragraphs (≥ 40 words) in assistant turns

import re

from .base import DetectedArtifact

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_DECISION_PATTERNS = [
    r"\bwe['\s]?ve decided\b",
    r"\bwe decided\b",
    r"\bthe decision is\b",
    r"\bdecided to\b",
    r"\bgoing with\b",
    r"\bsettled on\b",
    r"\bwe['\s]?ll go with\b",
    r"\bfinal decision\b",
    r"\bwe chose\b",
]

_ACTION_PATTERNS = [
    r"\b(TODO|todo)\b",
    r"\bnext step[s]?\b",
    r"\baction item[s]?\b",
    r"\bwe need to\b",
    r"\byou should\b",
    r"\bwe should\b",
    r"\bfollow[- ]up\b",
]

# Numbered or bulleted list lines (often actions in assistant responses)
_LIST_LINE_RE = re.compile(r"^[\d]+\.\s+(.+)$|^[-*]\s+(.+)$", re.MULTILINE)

_DECISION_RE = re.compile("|".join(_DECISION_PATTERNS), re.IGNORECASE)
_ACTION_RE = re.compile("|".join(_ACTION_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_artifacts(turns: list[dict]) -> list[DetectedArtifact]:
    """
    Run heuristic detection over parsed turns.
    Returns a list of DetectedArtifact objects (may be empty).
    """
    artifacts: list[DetectedArtifact] = []

    for idx, turn in enumerate(turns):
        text = (turn.get("text") or "").strip()
        if not text:
            continue

        speaker = turn.get("speaker", "")

        # --- Decisions (both speakers) ---
        for sentence in _split_sentences(text):
            if _DECISION_RE.search(sentence):
                title = _truncate(sentence, 120)
                body = sentence if len(sentence) > 120 else ""
                artifacts.append(DetectedArtifact(
                    kind="decision",
                    title=title,
                    body=body,
                    source_turn_idx=idx,
                ))

        # --- Questions (assistant turns — open, unresolved) ---
        if speaker == "assistant":
            for sentence in _split_sentences(text):
                if sentence.endswith("?") and len(sentence.split()) >= 5:
                    artifacts.append(DetectedArtifact(
                        kind="question",
                        title=_truncate(sentence, 140),
                        body="",
                        source_turn_idx=idx,
                    ))

        # --- Actions (both speakers) ---
        if _ACTION_RE.search(text):
            for sentence in _split_sentences(text):
                if _ACTION_RE.search(sentence):
                    title = _truncate(sentence, 120)
                    artifacts.append(DetectedArtifact(
                        kind="action",
                        title=title,
                        body="",
                        source_turn_idx=idx,
                    ))

        # --- Numbered/bulleted list items in assistant turns (likely actions) ---
        if speaker == "assistant":
            for match in _LIST_LINE_RE.finditer(text):
                item = (match.group(1) or match.group(2) or "").strip()
                if item and len(item.split()) >= 4:
                    artifacts.append(DetectedArtifact(
                        kind="action",
                        title=_truncate(item, 120),
                        body="",
                        source_turn_idx=idx,
                    ))

        # --- Annotations — notable assistant paragraphs (≥ 40 words) ---
        if speaker == "assistant":
            for para in text.split("\n\n"):
                para = para.strip()
                if len(para.split()) >= 40 and not _ACTION_RE.search(para):
                    artifacts.append(DetectedArtifact(
                        kind="annotation",
                        title=_truncate(para, 100),
                        body=para,
                        source_turn_idx=idx,
                    ))

    return _deduplicate(artifacts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Very light sentence splitter — splits on '. ', '! ', '? '."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n - 1].rstrip() + "…"


def _deduplicate(artifacts: list[DetectedArtifact]) -> list[DetectedArtifact]:
    """Remove near-duplicate titles (same kind + first 60 chars)."""
    seen: set[str] = set()
    out: list[DetectedArtifact] = []
    for a in artifacts:
        key = f"{a.kind}:{a.title[:60].lower()}"
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out
