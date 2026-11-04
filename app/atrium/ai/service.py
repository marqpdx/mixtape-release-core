# atrium/ai/service.py
#
# What an agent is told in an Atrium Dialogue, and the Continuous Keeper's triggers.
#
# ST-3 Part B (2026-11-04): every turn runs on the runtime worker, as the Dialogue
# owner's own account, one process per turn (atrium/turns.py). The adapters that ran
# Claude Code inside the API on the server's login, the Anthropic API adapter and the
# PUDDLEJUMP_GROUPS switch are gone. What stays here is provider-neutral: the system
# prompt, the opening context for an agent new to a Dialogue, the catch-up for one
# returning to it, the InitiativeLog lookup and the document envelope.

import logging
import re as _re

from cloud_agents.constants import PROVIDER_ANTHROPIC_CLAUDE_CODE, PROVIDER_OPENAI_CODEX

logger = logging.getLogger(__name__)

# P-1: Document signal protocol.
# When the AI generates a titled document (summary, spec, plan, ADR, etc.),
# it wraps the body in this XML envelope so the stream parser can switch
# rendering mode and display an AtriumDocCard instead of a prose bubble.
_DOC_SIGNAL_INSTRUCTION = (
    "\n\nDocument protocol: when you generate a structured document — a summary, "
    "spec, plan, ADR, finding, or similar titled artifact intended for saving — "
    "wrap the entire document body in an XML envelope:\n\n"
    "<document title=\"Your Document Title Here\">\n"
    "...document body in markdown...\n"
    "</document>\n\n"
    "Use this only for genuine document-shaped responses: multi-section or "
    "multi-paragraph artifacts with a clear title, intended as a standalone "
    "artifact. Do not wrap conversational replies, short answers, or inline "
    "code snippets."
)

# Compact one-liner added to each later turn, so a resumed agent keeps the protocol.
_DOC_PROTOCOL_HINT = (
    "[Atrium doc protocol: if this response is a titled document, wrap it in "
    "<document title=\"Title\">...markdown body...</document>]\n\n"
)

# Who said what, in the words every agent sees. The person is "Person".
SPEAKER_LABELS = {
    PROVIDER_ANTHROPIC_CLAUDE_CODE: "Claude",
    PROVIDER_OPENAI_CODEX: "Codex",
}


def speaker_label(entry) -> str:
    from atrium.models import DialogueEntryType, DialogueRole

    if entry.entry_type == DialogueEntryType.CHECKPOINT:
        return "Checkpoint (summary of the Dialogue before this point)"

    if entry.role == DialogueRole.USER:
        return "Person"
    return SPEAKER_LABELS.get(entry.speaker, "Agent")


# How many recent turns an agent new to a Dialogue is shown (token-bounded below).
_HISTORY_INJECT_TURNS = 10
# Approximate budget for that history, and for a returning agent's catch-up (tokens ≈ chars / 4).
_HISTORY_INJECT_MAX_CHARS = 16_000  # ~4 000 tokens
_CATCH_UP_MAX_CHARS = 16_000

# Idle-threshold in minutes per cadence setting.
_IDLE_THRESHOLDS = {"light": None, "steady": 30, "active": 10}
# Turn-count thresholds per cadence setting (count of finished replies).
_TURN_THRESHOLDS = {"light": None, "steady": 8, "active": 4}


# ---------------------------------------------------------------------------
# What an agent is told
# ---------------------------------------------------------------------------

def _build_system_prompt(dialogue) -> str:
    from atrium.ai.context import ClioPersonalContextBuilder
    from atrium.ai.filters import get_persona_filter

    parts = [
        "You are an AI thinking partner for a member working inside Mixtape — "
        "a collaborative platform for creative and professional work. "
        "You help the member think clearly, plan effectively, and make good decisions. "
        "Be direct and specific. Match the depth of the question.",
        "\n\nThis is an Atrium Dialogue. More than one agent may take part: each earlier "
        "turn is labelled with who said it (Person, Claude, Codex). When another agent "
        "answered, you may be asked what you make of its answer.",
    ]

    if dialogue.sponsor_object_id:
        sponsor = dialogue.sponsor
        if sponsor is not None:
            sponsor_slug = getattr(sponsor, "slug", None)
            sponsor_title = getattr(sponsor, "title", None) or getattr(sponsor, "username", str(sponsor))
            sponsor_summary = getattr(sponsor, "summary", "") or ""
            sponsor_type = dialogue.sponsor_content_type.model if dialogue.sponsor_content_type_id else "unknown"
            sponsor_line = f"{sponsor_type.capitalize()}: {sponsor_title}"
            if sponsor_slug:
                sponsor_line += f" (slug: {sponsor_slug})"
            if sponsor_summary:
                sponsor_line += f" — {sponsor_summary.strip()}"
            parts.append(f"\n\nSponsor context:\n{sponsor_line}")

    persona_filter = get_persona_filter(dialogue)
    if persona_filter:
        parts.append(f"\n\n{persona_filter}")

    if dialogue.session_context and dialogue.session_context.strip():
        parts.append(f"\n\nSession context:\n{dialogue.session_context.strip()}")

    personal_ctx = ClioPersonalContextBuilder().build(dialogue)
    if personal_ctx:
        parts.append(f"\n\nPersonal context:\n{personal_ctx}")

    parts.append(_DOC_SIGNAL_INSTRUCTION)

    return "\n".join(parts)


def _format_turns(entries, char_budget: int) -> list[str]:
    """Newest-last labelled lines, dropping the oldest when over budget."""
    lines: list[str] = []
    for entry in reversed(entries):
        text = (entry.content or "").strip()
        if not text:
            continue
        line = f"{speaker_label(entry)}: {text}"
        if len(line) > char_budget:
            break
        lines.append(line)
        char_budget -= len(line)
    lines.reverse()
    return lines


def build_opening_prompt(dialogue, message: str, *, before) -> tuple[str, str]:
    """
    Everything an agent new to this Dialogue needs, then the person's message.

    `before` is the created_at of the person's entry: only what came before it counts
    as history. Returns (prompt, provenance note).
    """
    from atrium.models import DialogueEntry, DialogueEntryStatus, DialogueEntryType

    parts = [_build_system_prompt(dialogue).strip()]
    provenance: list[str] = []

    # After a compact, the checkpoint stands in for everything before it.
    checkpoint = latest_checkpoint(dialogue, before=before)
    if checkpoint:
        parts.append(
            "[Checkpoint — the Dialogue so far, summarized]\n"
            + checkpoint.content.strip()
            + "\n[End checkpoint]"
        )
        provenance.append("checkpoint")

    log, _ = _resolve_initiative_log(dialogue)
    if checkpoint:
        pass  # the checkpoint already carries the Dialogue's summary
    elif log and log.compact_summary:
        ts = log.compact_at.strftime("%Y-%m-%d") if log.compact_at else "prior"
        parts.append(
            f"[Compact summary — distilled {ts}]\n{log.compact_summary.strip()}\n[End compact summary]"
        )
        provenance.append(f"compact summary ({ts})")
    elif log and log.import_source:
        imported = _imported_log_block(log)
        if imported:
            parts.append(imported[0])
            provenance.append(imported[1])

    history_qs = DialogueEntry.objects.filter(
        dialogue=dialogue,
        created_at__lt=before,
        status=DialogueEntryStatus.DONE,
    ).exclude(entry_type=DialogueEntryType.CHECKPOINT)
    if checkpoint:
        history_qs = history_qs.filter(created_at__gt=checkpoint.created_at)
    history = list(history_qs.order_by("-created_at")[: _HISTORY_INJECT_TURNS * 2])
    history.reverse()
    lines = _format_turns(history, _HISTORY_INJECT_MAX_CHARS)
    if lines:
        parts.append(
            "[This Dialogue so far — most recent turns]\n"
            + "\n".join(lines)
            + "\n[End of earlier turns — the Person's new message follows]"
        )
        provenance.append(f"last {len(lines)} turn(s)")

    parts.append(f"Person: {message}")
    note = "Opened with " + " + ".join(provenance) + "." if provenance else "Opened fresh."
    return "\n\n".join(parts), note


def _imported_log_block(log) -> tuple[str, str] | None:
    """
    When the InitiativeLog was filled by import_conversation and has no compact summary
    yet, a window of the imported turns, so the agent has the source material.
    """
    from initiatives.models import InitiativeLogEntry, InitiativeLogEntryKind

    prose_entries = list(
        InitiativeLogEntry.objects.filter(
            initiative_log=log,
            kind=InitiativeLogEntryKind.PROSE,
        ).order_by("source_turn_index", "created_at")[:60]
    )
    turn_lines = []
    char_budget = 12000
    for e in prose_entries:
        role_label = "Person" if e.authored_by not in ("claude", "system") else "Assistant"
        line = f"{role_label}: {e.body.strip()}"
        if len(line) > char_budget:
            break
        turn_lines.append(line)
        char_budget -= len(line)
    if not turn_lines:
        return None
    source_title = log.import_source.get("title", "imported conversation")
    n_shown = len([line for line in turn_lines if line.startswith("Person:")])
    n_total = InitiativeLogEntry.objects.filter(
        initiative_log=log, kind=InitiativeLogEntryKind.PROSE
    ).count()
    block = (
        f"[Imported conversation: {source_title} — showing {n_shown} of {n_total // 2} exchanges]\n"
        + "\n".join(turn_lines)
        + "\n[End imported conversation — this is the source material for curation]"
    )
    return block, f"imported log ({n_shown}/{n_total // 2} exchanges shown)"


def build_catch_up_prompt(dialogue, message: str, *, since, before) -> str:
    """
    For an agent returning to this Dialogue: what was said since it last took part
    (by the person and by any other agent), then the person's new message.
    """
    from atrium.models import DialogueEntry, DialogueEntryStatus, DialogueEntryType

    missed = list(
        DialogueEntry.objects.filter(
            dialogue=dialogue,
            created_at__gt=since,
            created_at__lt=before,
            status=DialogueEntryStatus.DONE,
        ).exclude(entry_type=DialogueEntryType.CHECKPOINT).order_by("created_at")
    )
    parts = []
    lines = _format_turns(missed, _CATCH_UP_MAX_CHARS)
    if lines:
        parts.append(
            "[Since your last turn in this Dialogue]\n"
            + "\n".join(lines)
            + "\n[End — the Person's new message follows]"
        )
    parts.append(_DOC_PROTOCOL_HINT + message)
    return "\n\n".join(parts)


def latest_checkpoint(dialogue, *, before=None):
    """The newest finished checkpoint (compact) in this Dialogue, optionally before a time."""
    from atrium.models import DialogueEntryStatus, DialogueEntryType

    qs = dialogue.entries.filter(entry_type=DialogueEntryType.CHECKPOINT, status=DialogueEntryStatus.DONE)
    if before is not None:
        qs = qs.filter(created_at__lt=before)
    return qs.order_by("-created_at").first()


def build_transcript(dialogue, max_chars: int = 40_000, *, since_checkpoint: bool = False, before=None) -> str:
    """
    The Dialogue as labelled lines, trimmed from the start when long. With
    since_checkpoint, it starts at the newest checkpoint (its summary, then what followed).
    """
    from atrium.models import DialogueEntryStatus

    qs = dialogue.entries.filter(status=DialogueEntryStatus.DONE)
    if before is not None:
        qs = qs.filter(created_at__lt=before)
    if since_checkpoint:
        checkpoint = latest_checkpoint(dialogue, before=before)
        if checkpoint:
            qs = qs.filter(created_at__gte=checkpoint.created_at)
    lines = [
        f"{speaker_label(entry)}: {(entry.content or '').strip()}"
        for entry in qs.order_by("created_at")
        if (entry.content or "").strip()
    ]
    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[-max_chars:]
    return transcript


# ---------------------------------------------------------------------------
# Dialogue / Initiative resolution
# ---------------------------------------------------------------------------

def _resolve_initiative_log(dialogue):
    """
    Navigate from a Dialogue to its Initiative's InitiativeLog.

    Uses the Dialogue's own Initiative when set; else the Initiative whose sponsor is
    the Dialogue's sponsor; else the member's personal Initiative.
    Returns (InitiativeLog, cadence) or (None, "steady").
    """
    if dialogue is None:
        return None, "steady"
    try:
        from initiatives.models import InitiativeLog, Initiative

        if dialogue.initiative_id:
            initiative = Initiative.objects.filter(
                id=dialogue.initiative_id, deleted_at__isnull=True
            ).first()
        elif dialogue.sponsor_content_type_id and dialogue.sponsor_object_id:
            initiative = Initiative.objects.filter(
                sponsor_content_type_id=dialogue.sponsor_content_type_id,
                sponsor_object_id=dialogue.sponsor_object_id,
                deleted_at__isnull=True,
            ).first()
        else:
            from django.contrib.contenttypes.models import ContentType
            member = dialogue.member
            ct = ContentType.objects.get_for_model(member)
            initiative = Initiative.objects.filter(
                sponsor_content_type=ct,
                sponsor_object_id=member.pk,
                is_personal=True,
                deleted_at__isnull=True,
            ).first()

        if initiative is None:
            return None, "steady"

        log = InitiativeLog.objects.filter(initiative=initiative).first()
        cadence = getattr(log, "compact_cadence", "steady") if log else "steady"
        return log, cadence

    except Exception as exc:
        logger.warning("[atrium] _resolve_initiative_log failed: %s", exc)
        return None, "steady"


# ---------------------------------------------------------------------------
# Continuous Keeper (K-4): background compaction triggers
# ---------------------------------------------------------------------------

def _continuous_keeper_id(dialogue) -> str:
    """
    Keeper ADR AD-8-style parameterized instance id — one Continuous Keeper
    "instance" per Dialogue, matching CountNagKeeper's own dot-separated
    instance convention (e.g. count-nag-keeper.junk-pile).
    """
    return f"continuous-keeper.{dialogue.id}"


def _ensure_continuous_keeper_registered(dialogue, cadence: str) -> None:
    """
    K-4: register this Dialogue's Continuous Keeper with Clio (AD-3/AD-4 —
    all Keepers register, no exceptions) the first time it becomes active.
    Idempotent — safe to call on every trigger check.

    No question_shapes: Continuous Keeper never answers routed questions
    (AD-2 permits this for proactive-only Keepers). closing_mode is "drop"
    since a Dialogue-scoped registration has no lineage value once it ends.
    """
    try:
        from clio import services as clio_services

        clio_services.ensure_keeper_registered(
            keeper_id=_continuous_keeper_id(dialogue),
            keeper_name="Continuous Keeper",
            owner_subsystem="atrium",
            watch_scope=(
                f"DialogueEntry rows for Dialogue {dialogue.id}; triggers on turn-count/idle "
                f"thresholds per Thermostat cadence (Phase 2D)."
            ),
            finding_cadence="proactive",
            closing_mode="drop",
            instance_params={"session_id": str(dialogue.id), "compact_cadence": cadence},
        )
    except Exception as exc:
        # Registration is Keeper-pattern bookkeeping, not correctness-critical
        # for the compaction itself (mirrors the ADR's own Celery-down stance).
        logger.warning("[atrium] Continuous Keeper registration failed for Dialogue %s: %s", dialogue.id, exc)


def _queue_keeper_compact(dialogue, cadence: str) -> None:
    _ensure_continuous_keeper_registered(dialogue, cadence)
    from atrium.tasks import keeper_compact_task
    keeper_compact_task.delay(str(dialogue.id))


def _trigger_keeper_if_due(dialogue) -> None:
    """
    Fire the Continuous Keeper task if the turn threshold for this Dialogue's
    cadence has been reached. Called when a reply is finished (atrium/signals.py).
    """
    try:
        log, cadence = _resolve_initiative_log(dialogue)
        threshold = _TURN_THRESHOLDS.get(cadence)
        if threshold is None:
            return  # "light" cadence — no turn-count trigger

        from atrium.models import DialogueEntry, DialogueEntryStatus, DialogueRole
        since = getattr(log, "compact_at", None)
        qs = DialogueEntry.objects.filter(
            dialogue=dialogue,
            role=DialogueRole.ASSISTANT,
            status=DialogueEntryStatus.DONE,
        )
        if since:
            qs = qs.filter(created_at__gt=since)
        if qs.count() >= threshold:
            _queue_keeper_compact(dialogue, cadence)
    except Exception as exc:
        logger.warning("[atrium] _trigger_keeper_if_due failed: %s", exc)


def _trigger_idle_keeper_if_due(dialogue) -> None:
    """
    Fire the Continuous Keeper task if the Dialogue has been idle past the cadence
    threshold. Called when the person sends a message, before the turn is queued.

    Dialogue.last_activity_at holds the time of the last finished turn, which is
    what "idle since" means here. Backfilled onto the InitiativeLog's
    last_session_end for any other consumer that expects it.
    """
    try:
        from django.utils import timezone
        log, cadence = _resolve_initiative_log(dialogue)
        if log is None:
            return
        idle_minutes = _IDLE_THRESHOLDS.get(cadence)
        if idle_minutes is None:
            return  # "light" cadence — no idle trigger

        last_end = dialogue.last_activity_at
        if last_end is None:
            return

        if log.last_session_end != last_end:
            log.last_session_end = last_end
            log.save(update_fields=["last_session_end", "updated_at"])

        last_compact = getattr(log, "compact_at", None)
        idle_delta = (timezone.now() - last_end).total_seconds() / 60
        if idle_delta >= idle_minutes and (last_compact is None or last_compact < last_end):
            _queue_keeper_compact(dialogue, cadence)
    except Exception as exc:
        logger.warning("[atrium] _trigger_idle_keeper_if_due failed: %s", exc)


# ---------------------------------------------------------------------------
# Document envelope
# ---------------------------------------------------------------------------

_DOCUMENT_OPEN_RE = _re.compile(r'<document(?:\s+title="([^"]*)")?[^>]*>', _re.DOTALL)


def _parse_document_envelope(text: str) -> tuple:
    """
    Detect a <document title="...">...</document> envelope.
    Returns (entry_type, document_title, body).
    If the envelope is absent or incomplete, returns ("message", "", text).
    Body is stripped of the envelope tags; document_title may be empty string.
    """
    from atrium.models import DialogueEntryType
    m = _DOCUMENT_OPEN_RE.search(text)
    if not m:
        return DialogueEntryType.MESSAGE, "", text
    title = m.group(1) or ""
    body = text[m.end():]
    close_idx = body.rfind("</document>")
    if close_idx == -1:
        # Opened but never closed — stream was interrupted; fall back to message.
        return DialogueEntryType.MESSAGE, "", text
    body = body[:close_idx].strip()
    return DialogueEntryType.DOCUMENT, title, body
