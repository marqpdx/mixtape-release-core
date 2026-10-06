# folio/services/note_search.py
#
# Folio Notes PoC Phase 4 — retrieval (folio-notes-poc-handoff.md addendum §3).
#
# Stackroom does the semantic match only, over FolioNotes ingested as
# artifact_type "folio_note" by inkwell's FolioNoteAdapter. Everything the
# writer can correct — Shape, confirmed entities — plus Folio scoping and
# recency is filtered here in Postgres, where the authoritative values live.

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType

from folio.models import Folio, FolioNote
from folio.shapes import effective_shape_q
from inkwell.models import StackroomSyncState
from inkwell.stackroom_adapters.folio_note import FOLIO_NOTE_ARTIFACT_TYPE, FolioNoteAdapter
from stackroom_client import retrieve

# Stackroom ranks across the writer's whole library (every Folio); over-fetch
# so Folio/Shape/entity filtering still leaves `limit` results to show.
_SEMANTIC_OVERFETCH = 5
_SEMANTIC_MAX = 200


@dataclass
class NoteHit:
    note: FolioNote
    score: float | None = None


def _filtered(folio: Folio, *, shape: str | None, entity_id: str | None):
    qs = folio.notes.all()
    if shape:
        qs = qs.filter(effective_shape_q(shape))
    if entity_id:
        # Only writer-confirmed links count; unconfirmed candidates are suggestions.
        qs = qs.filter(mentions__contains=[{"confirmed_entity_id": str(entity_id)}])
    return qs


def search_folio_notes(
    folio: Folio,
    *,
    user,
    query: str = "",
    shape: str | None = None,
    entity_id: str | None = None,
    limit: int = 20,
) -> list[NoteHit]:
    """Semantic search when `query` is given, else most recent first. Raises
    stackroom_client.StackroomClientError if Stackroom can't be reached."""
    qs = _filtered(folio, shape=shape, entity_id=entity_id)
    query = (query or "").strip()
    if not query:
        return [NoteHit(note) for note in qs.order_by("-created_at")[:limit]]

    library_id = getattr(user, "stackroom_library_id", None)
    if not library_id:
        return []  # nothing of this writer's has been indexed yet

    results = retrieve(
        query=query,
        library_id=library_id,
        limit=min(limit * _SEMANTIC_OVERFETCH, _SEMANTIC_MAX),
        artifact_types=[FOLIO_NOTE_ARTIFACT_TYPE],
    )
    # A long note can come back as several chunks; keep its best score.
    best: dict[str, float] = {}
    for r in results:
        sfid = str(r.get("source_file_id") or "")
        if sfid:
            best[sfid] = max(best.get(sfid, float("-inf")), float(r.get("score") or 0.0))
    if not best:
        return []

    note_ct = ContentType.objects.get_for_model(FolioNote, for_concrete_model=False)
    note_scores: dict[str, float] = {}
    for object_id, sfid in StackroomSyncState.objects.filter(
        content_type=note_ct,
        adapter_name=FolioNoteAdapter.adapter_name,
        stackroom_source_file_id__in=list(best),
    ).values_list("object_id", "stackroom_source_file_id"):
        note_scores[object_id] = max(note_scores.get(object_id, float("-inf")), best[str(sfid)])

    notes = qs.filter(pk__in=list(note_scores))
    hits = [NoteHit(note, note_scores[str(note.pk)]) for note in notes]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]
