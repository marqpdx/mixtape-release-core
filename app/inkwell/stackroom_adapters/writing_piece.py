from __future__ import annotations

from uuid import UUID

from inkwell.stackroom_http_client import get_or_create_group_library, get_or_create_user_library
from utils.writing.writing_utils import extract_text_from_prosemirror
from writing.models import WritingPiece

from .base import BaseStackroomAdapter


class WritingPieceAdapter(BaseStackroomAdapter):
    adapter_name = "writing_piece"

    def supports(self, obj) -> bool:
        return isinstance(obj, WritingPiece)

    def build_text(self, piece: WritingPiece) -> str:
        parts: list[str] = []

        def add(label: str, value) -> None:
            v = (value or "").strip()
            if v:
                parts.append(f"{label}:\n{v}")

        add("Title", piece.title)
        add("Excerpt", getattr(piece, "excerpt", None))
        add("Writing Kind", piece.writing_kind)
        add("Status", piece.status)
        add("Body", extract_text_from_prosemirror(piece.body_json or {}))
        return "\n\n".join(parts)

    def get_library_id(self, piece: WritingPiece) -> UUID:
        if (piece.sponsor_content_type and
                piece.sponsor_content_type.model == "group"):
            group_model = piece.sponsor_content_type.model_class()
            group = group_model.objects.get(pk=piece.sponsor_object_id)
            return get_or_create_group_library(group)
        user = piece.author or getattr(piece, "submitted_by", None)
        return get_or_create_user_library(user)

    def get_source_path(self, piece: WritingPiece) -> str:
        if (piece.sponsor_content_type and
                piece.sponsor_content_type.model == "group"):
            return f"writing_pieces/groups/{piece.sponsor_object_id}/{piece.pk}.txt"
        user_id = piece.author_id or getattr(piece, "submitted_by_id", "unknown")
        return f"writing_pieces/{user_id}/{piece.pk}.txt"
