# initiatives/services/initiative_radar.py
#
# Service layer for the personal work radar (W-16).
# All operations are synchronous and user-driven — no AI in Phase 1.

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from initiatives.importers import chatgpt_parser, claude_parser, freeform_parser
from initiatives.importers.base import ImportParseError
from initiatives.models import (
    Initiative,
    InitiativeArtifact,
    InitiativeArtifactType,
    InitiativeStatus,
    ConversationSource,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Initiative CRUD
# ---------------------------------------------------------------------------

def create_initiative(user, *, title: str, direction: str = "") -> Initiative:
    """
    Create a new personal radar initiative owned by `user`.

    Position is set to one past the highest position among the user's
    non-archived initiatives, so new items land at the bottom of active.
    """
    sponsor_ct = ContentType.objects.get_for_model(user.__class__)
    max_pos = (
        Initiative.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=user.pk,
        )
        .exclude(status=InitiativeStatus.ARCHIVED)
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
    ) or 0

    return Initiative.objects.create(
        title=title,
        direction=direction,
        status=InitiativeStatus.ACTIVE,
        sponsor_content_type=sponsor_ct,
        sponsor_object_id=user.pk,
        created_by=user,
        position=max_pos + 1,
    )


def update_initiative(initiative: Initiative, **fields: Any) -> Initiative:
    """
    Update allowed fields on a personal initiative.

    Accepted keys: title, direction, narrative, last_session_note, status.
    Ignores unknown keys to avoid accidental overwrites.
    """
    allowed = {"title", "direction", "narrative", "last_session_note", "status"}
    dirty = []
    for key, value in fields.items():
        if key in allowed:
            setattr(initiative, key, value)
            dirty.append(key)

    if dirty:
        initiative.save(update_fields=dirty + ["updated_at"])

    return initiative


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

def set_status(initiative: Initiative, status: str) -> Initiative:
    """
    Transition initiative status. Active ↔ Paused freely.
    Archived is one-way from the UI — no restore from archived via this path.
    Use restore_initiative() to move archived → paused.
    """
    if initiative.status == InitiativeStatus.ARCHIVED and status != InitiativeStatus.ARCHIVED:
        raise ValueError("Use restore_initiative() to unarchive an initiative.")
    initiative.status = status
    initiative.save(update_fields=["status", "updated_at"])
    return initiative


def archive_initiative(initiative: Initiative) -> Initiative:
    initiative.status = InitiativeStatus.ARCHIVED
    initiative.save(update_fields=["status", "updated_at"])
    return initiative


def restore_initiative(initiative: Initiative) -> Initiative:
    """Move an archived initiative back to paused."""
    if initiative.status != InitiativeStatus.ARCHIVED:
        raise ValueError("Only archived initiatives can be restored.")
    initiative.status = InitiativeStatus.PAUSED
    initiative.save(update_fields=["status", "updated_at"])
    return initiative


# ---------------------------------------------------------------------------
# Reordering
# ---------------------------------------------------------------------------

@transaction.atomic
def reorder_initiatives(user, ordered_ids: list[str | UUID]) -> None:
    """
    Set position on each initiative by the supplied list order (0-indexed + 1).

    Only reorders initiatives owned by `user`. Ignores IDs that don't belong
    to this user. Active and paused initiatives share the same position space
    within their section; callers should supply only the IDs within one status
    section at a time.
    """
    sponsor_ct = ContentType.objects.get_for_model(user.__class__)
    qs = Initiative.objects.filter(
        sponsor_content_type=sponsor_ct,
        sponsor_object_id=user.pk,
        id__in=[str(i) for i in ordered_ids],
    )
    by_id = {str(obj.id): obj for obj in qs}

    to_update = []
    for pos, raw_id in enumerate(ordered_ids, start=1):
        obj = by_id.get(str(raw_id))
        if obj and obj.position != pos:
            obj.position = pos
            to_update.append(obj)

    if to_update:
        Initiative.objects.bulk_update(to_update, ["position", "updated_at"])


# ---------------------------------------------------------------------------
# Artifact operations
# ---------------------------------------------------------------------------

def add_doc_link(
    initiative: Initiative,
    *,
    label: str,
    doc_path: str,
) -> InitiativeArtifact:
    """Attach a puddlejump document path to an initiative."""
    pos = _next_artifact_position(initiative)
    return InitiativeArtifact.objects.create(
        initiative=initiative,
        artifact_type=InitiativeArtifactType.DOC_LINK,
        label=label,
        doc_path=doc_path,
        position=pos,
    )


def import_conversation(
    initiative: Initiative,
    *,
    label: str,
    raw_json: bytes | str,
) -> InitiativeArtifact:
    """
    Parse and store a Claude or ChatGPT conversation export.

    `raw_json` is the raw file bytes or string. The parser is auto-detected.
    Raises ImportParseError if the data cannot be parsed.
    """
    if isinstance(raw_json, bytes):
        raw_json = raw_json.decode("utf-8")

    data = json.loads(raw_json)

    if claude_parser.looks_like_claude_export(data):
        parsed = claude_parser.parse(data)
        source = ConversationSource.CLAUDE
    elif _looks_like_chatgpt_export(data):
        parsed = chatgpt_parser.parse(data)
        source = ConversationSource.CHATGPT
    else:
        parsed = freeform_parser.parse(data)
        source = ConversationSource.OTHER

    transcript = _render_transcript(parsed.turns, source)
    pos = _next_artifact_position(initiative)

    return InitiativeArtifact.objects.create(
        initiative=initiative,
        artifact_type=InitiativeArtifactType.CONVERSATION_IMPORT,
        label=label or parsed.conversation_title,
        conversation_source=source,
        conversation_json=data,
        conversation_text=transcript,
        position=pos,
    )


@transaction.atomic
def reorder_artifacts(initiative: Initiative, ordered_ids: list[str | UUID]) -> None:
    """Set position on each artifact by the supplied list order."""
    qs = InitiativeArtifact.objects.filter(
        initiative=initiative,
        id__in=[str(i) for i in ordered_ids],
    )
    by_id = {str(obj.id): obj for obj in qs}

    to_update = []
    for pos, raw_id in enumerate(ordered_ids, start=1):
        obj = by_id.get(str(raw_id))
        if obj and obj.position != pos:
            obj.position = pos
            to_update.append(obj)

    if to_update:
        InitiativeArtifact.objects.bulk_update(to_update, ["position", "updated_at"])


def remove_artifact(artifact: InitiativeArtifact) -> None:
    artifact.delete()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_artifact_position(initiative: Initiative) -> int:
    max_pos = (
        InitiativeArtifact.objects.filter(initiative=initiative)
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
    ) or 0
    return max_pos + 1


def _looks_like_chatgpt_export(data: list | dict) -> bool:
    try:
        convs = data if isinstance(data, list) else [data]
        return bool(convs) and "mapping" in convs[0]
    except Exception:
        return False


SPEAKER_LABELS = {
    ConversationSource.CLAUDE: {"human": "You", "assistant": "Claude"},
    ConversationSource.CHATGPT: {"human": "You", "assistant": "GPT"},
    ConversationSource.OTHER: {"human": "You", "assistant": "Assistant"},
}


def _render_transcript(turns, source: str) -> str:
    """Flat chronological plain-text transcript with speaker labels."""
    labels = SPEAKER_LABELS.get(source, SPEAKER_LABELS[ConversationSource.OTHER])
    lines = []
    for turn in turns:
        speaker = labels.get(turn.speaker, turn.speaker.capitalize())
        lines.append(f"{speaker}: {turn.text.strip()}")
    return "\n\n".join(lines)
