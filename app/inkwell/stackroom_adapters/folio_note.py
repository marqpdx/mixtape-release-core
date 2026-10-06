from __future__ import annotations

from uuid import UUID

from folio.models import FolioNote
from stackroom_client import get_or_create_user_library

from .base import BaseStackroomAdapter

FOLIO_NOTE_ARTIFACT_TYPE = "folio_note"


class FolioNoteAdapter(BaseStackroomAdapter):
    """Folio Notes PoC Phase 4 — retrieval only. Embeds the note's text alone
    (raw text, or transcript for voice): Shape, mentions and Folio stay in
    Postgres and are filtered there, so corrections never need a re-sync
    (folio-notes-poc-handoff.md addendum §3)."""

    adapter_name = "folio_note"
    artifact_type = FOLIO_NOTE_ARTIFACT_TYPE

    def supports(self, obj) -> bool:
        return isinstance(obj, FolioNote)

    def build_text(self, note: FolioNote) -> str:
        if not note.created_by_id:
            return ""  # no owner library to index into; ingest skips empty text
        return (note.text or "").strip()

    def get_library_id(self, note: FolioNote) -> UUID:
        return get_or_create_user_library(note.created_by)

    def get_source_path(self, note: FolioNote) -> str:
        return f"folio_notes/{note.created_by_id}/{note.pk}.txt"
