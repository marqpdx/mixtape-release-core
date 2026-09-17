# console/inbox_keeper.py
#
# InboxKeeper (Keeper ADR keeper-library.md, K-7). Advisory-only, async
# scan of Reception's formless capture queue (console.HubCapture). Guesses
# a content-type label for a landed capture ("this looks like a shopping
# item") without transforming, filing, or acting on the capture itself —
# pure advisory finding (K-3 store-and-defer).
#
# Classification is heuristic keyword/pattern matching over
# scrap.IntentTag's existing vocabulary (same taxonomy platform-wide,
# rather than inventing a second one) — no LLM call, no per-capture cost
# or latency in the capture-creation path. Rougher guesses than an LLM
# classifier, chosen deliberately for a first cut (see keeper-adr-status.md).
#
# The two Celery tasks (registration heartbeat, answer_task) live in
# console/tasks.py alongside this subsystem's other tasks; this module
# holds the plain-function logic so it's directly testable/importable.

import logging
import re

logger = logging.getLogger(__name__)

KEEPER_ID = "inbox-keeper"
INTENT = "inbox_type_guess"

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{7,}\d)")
_RECIPE_WORDS = re.compile(r"\b(recipe|ingredients?|tbsp|tsp|cup|bake|oven|simmer|whisk)\b", re.IGNORECASE)
_REMINDER_WORDS = re.compile(r"\b(remind|don'?t forget|remember to)\b", re.IGNORECASE)
_IDEA_WORDS = re.compile(r"\b(idea|what if|maybe we should)\b", re.IGNORECASE)
_LIST_SPLIT_RE = re.compile(r"[,;]\s*|\n+")
_MAX_LIST_ITEM_WORDS = 8


def _looks_like_list(text: str) -> bool:
    """Same shape heuristic as console/tasks.py's _parse_capture_list — several
    short comma/newline-separated items reads as a list, not one long thought."""
    parts = [p.strip() for p in _LIST_SPLIT_RE.split(text) if p.strip()]
    if len(parts) < 2:
        return False
    avg_words = sum(len(p.split()) for p in parts) / len(parts)
    return avg_words <= _MAX_LIST_ITEM_WORDS


def guess_capture_type(body: str) -> dict:
    """
    Heuristic content-type guess over scrap.IntentTag's vocabulary. Returns
    {"guessed_type": <IntentTag value>, "confidence": float 0-1}. Checked
    most-specific pattern first; falls back to "note" at low confidence.
    """
    text = (body or "").strip()
    if not text:
        return {"guessed_type": "note", "confidence": 0.0}

    if text.endswith("?"):
        return {"guessed_type": "question", "confidence": 0.7}
    if _URL_RE.search(text):
        return {"guessed_type": "link", "confidence": 0.9}
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        return {"guessed_type": "contact", "confidence": 0.8}
    if _RECIPE_WORDS.search(text):
        return {"guessed_type": "recipe", "confidence": 0.7}
    if _REMINDER_WORDS.search(text):
        return {"guessed_type": "reminder", "confidence": 0.7}
    if _IDEA_WORDS.search(text):
        return {"guessed_type": "idea", "confidence": 0.6}
    if _looks_like_list(text):
        return {"guessed_type": "list", "confidence": 0.6}
    return {"guessed_type": "note", "confidence": 0.3}


def ensure_inbox_keeper_registered() -> None:
    """
    Idempotent AD-10 registration. A single global Keeper (unlike K-6's
    per-owner CountNagKeeper instances) — Reception has one formless
    capture queue, not one per owner, matching keeper-library.md's "Reception
    spawns InboxKeeper" (singular). finding_cadence "both": proactive async
    scan on new entries (this module's check_and_submit_guess) + reactive
    on-demand type-guess query. closing_mode "archive" per keeper-library.md.
    """
    try:
        from clio import services as clio_services

        clio_services.ensure_keeper_registered(
            keeper_id=KEEPER_ID,
            keeper_name="InboxKeeper",
            owner_subsystem="console",
            watch_scope=(
                "console.HubCapture rows landing in Reception's formless capture "
                "queue (status open/processing) — advisory content-type guess "
                "only, never transforms, files, or acts on the capture."
            ),
            question_shapes=[
                {
                    "intent": INTENT,
                    "description": "What does this inbox entry look like?",
                    "answer_task": "console.tasks.answer_inbox_type_guess",
                }
            ],
            finding_cadence="both",
            closing_mode="archive",
            instance_params={},
        )
    except Exception as exc:
        logger.warning("[inbox-keeper] registration failed: %s", exc)


def check_and_submit_guess(capture) -> None:
    """
    Called from console/signals.py when a HubCapture lands with real body
    text — a direct text capture on creation, or an audio capture
    transitioning PROCESSING -> OPEN once transcription completes. Submits
    one proactive K-3 store-and-defer finding per capture; no dedup needed,
    a given capture only crosses this path once in its normal lifecycle.
    """
    try:
        from clio import services as clio_services

        ensure_inbox_keeper_registered()
        guess = guess_capture_type(capture.body)
        clio_services.submit_finding(
            keeper_id=KEEPER_ID,
            finding_type="inbox_type_guess",
            finding_body={
                "capture_id": str(capture.id),
                "guessed_type": guess["guessed_type"],
                "confidence": guess["confidence"],
                "body_snippet": (capture.body or "")[:80],
            },
            suggested_clio_signal="suggest",
        )
    except Exception as exc:
        logger.warning("[inbox-keeper] guess submission failed for capture %s: %s", capture.id, exc)
