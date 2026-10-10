# folio/services/workbench.py
#
# Folio Notes PoC Phase 5 — Desktop Workbench support (build plan §34, §55).
# Facet counts, Folio-level mention → Entity association, and related notes.
#
# Entities are the shared storyboard.Entity (folio-notes-poc-handoff.md
# addendum §2), sponsored by the writer — the same scope tending's
# match_entity_alias already searches — so an Entity confirmed here is the
# same row a Storyboard participant uses, and vice versa.

from __future__ import annotations

from collections import Counter

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from folio.models import Folio, FolioNote
from folio.services.note_search import NoteHit, search_folio_notes
from folio.shapes import Shape, effective_shape
from storyboard.models import Entity

# Mentions arrive from tending with these kinds (folio.tasks). Entity.kind is a
# plain string, so these are stored as-is.
MENTION_KINDS = ("character", "setting", "thing", "concept")


def _sponsor(user) -> dict:
    return {
        "sponsor_content_type": ContentType.objects.get_for_model(user),
        "sponsor_object_id": user.pk,
    }


def writer_entities(user):
    return Entity.objects.filter(**_sponsor(user))


def folio_facets(folio: Folio) -> dict:
    """Counts for the Workbench's left column: every Shape (zero included, so
    the column is stable) and the Entities writers have confirmed in this
    Folio's notes. PoC scale — computed in Python over the Folio's notes."""
    shapes = Counter()
    entity_counts = Counter()
    total = 0
    for suggested, confirmed, mentions in folio.notes.values_list("suggested_shape", "confirmed_shape", "mentions"):
        total += 1
        shapes[effective_shape(suggested, confirmed)] += 1
        seen = {m.get("confirmed_entity_id") for m in (mentions or []) if isinstance(m, dict)}
        for entity_id in seen - {None, ""}:
            entity_counts[entity_id] += 1

    entities = []
    if entity_counts:
        for entity in Entity.objects.filter(pk__in=list(entity_counts)):
            entities.append({"id": str(entity.id), "name": entity.name, "kind": entity.kind,
                             "count": entity_counts[str(entity.id)]})
        entities.sort(key=lambda e: (-e["count"], e["name"].casefold()))
    return {
        "total": total,
        "shapes": [{"shape": value, "count": shapes[value]} for value in Shape.values],
        "entities": entities,
    }


def _mention(note: FolioNote, index: int) -> dict:
    if not isinstance(note.mentions, list) or not 0 <= index < len(note.mentions) \
            or not isinstance(note.mentions[index], dict):
        raise ValidationError("Choose a valid mention.")
    return note.mentions[index]


@transaction.atomic
def confirm_mention(note: FolioNote, index: int, *, user, entity_id=None, name: str = "", kind: str | None = None):
    """Writer confirms what a mention refers to: an existing Entity of theirs,
    or a new one named here. Only `confirmed_*` keys change on the mention —
    the model's surface/kind/confidence stay for provenance (§12)."""
    note = FolioNote.objects.select_for_update().get(pk=note.pk)
    mention = _mention(note, index)
    kind = kind or mention.get("kind") or "thing"
    if entity_id:
        try:
            entity = writer_entities(user).get(pk=entity_id)
        except Entity.DoesNotExist:
            raise ValidationError("That Entity isn't available.")
    else:
        name = (name or mention.get("surface") or "").strip()
        if not name:
            raise ValidationError("A new Entity needs a name.")
        entity = Entity.objects.create(kind=kind, name=name, created_by=user, **_sponsor(user))
    surface = (mention.get("surface") or "").strip()
    if surface and surface.casefold() != entity.name.casefold() and \
            surface.casefold() not in {a.casefold() for a in entity.aliases if isinstance(a, str)}:
        # Remember how the writer refers to it, so tending's alias match
        # suggests this Entity next time.
        entity.aliases = [*entity.aliases, surface]
        entity.save(update_fields=["aliases", "updated_at"])
    mention["confirmed_entity_id"] = str(entity.id)
    mention["confirmed_kind"] = entity.kind
    note.save(update_fields=["mentions", "updated_at"])
    return note, entity


@transaction.atomic
def unlink_mention(note: FolioNote, index: int) -> FolioNote:
    note = FolioNote.objects.select_for_update().get(pk=note.pk)
    mention = _mention(note, index)
    mention.pop("confirmed_entity_id", None)
    mention.pop("confirmed_kind", None)
    note.save(update_fields=["mentions", "updated_at"])
    return note


def related_notes(note: FolioNote, *, user, limit: int = 5) -> list[NoteHit]:
    """Nearest neighbours in the same Folio — a retrieval affordance only,
    never stored as a relationship (build plan §29)."""
    text = (note.text or "").strip()
    if not text:
        return []
    hits = search_folio_notes(note.folio, user=user, query=text[:2000], limit=limit + 1)
    return [hit for hit in hits if hit.note.pk != note.pk][:limit]
