from __future__ import annotations

from uuid import UUID

from inkwell.stackroom_http_client import get_or_create_user_library
from utils.writing.writing_utils import extract_text_from_prosemirror
from writing.models import WorkingDocument

from .base import BaseStackroomAdapter


class WorkingDocumentAdapter(BaseStackroomAdapter):
    adapter_name = "working_document"

    def supports(self, obj) -> bool:
        return isinstance(obj, WorkingDocument)

    def build_text(self, doc: WorkingDocument) -> str:
        parts: list[str] = []

        def add(label: str, value) -> None:
            v = (value or "").strip()
            if v:
                parts.append(f"{label}:\n{v}")

        add("Title", doc.title)
        add("Excerpt", getattr(doc, "excerpt", None))
        add("Body", extract_text_from_prosemirror(doc.body_json or {}))
        return "\n\n".join(parts)

    def get_library_id(self, doc: WorkingDocument) -> UUID:
        return get_or_create_user_library(doc.user)

    def get_source_path(self, doc: WorkingDocument) -> str:
        return f"working_documents/{doc.user_id}/{doc.pk}.txt"
