from __future__ import annotations

from uuid import UUID

from inkwell.stackroom_http_client import get_or_create_user_library

from .base import BaseStackroomAdapter


class TranscriptAdapter(BaseStackroomAdapter):
    adapter_name = "media_capture_transcript"

    def supports(self, obj) -> bool:
        try:
            from media_capture.models import Transcript
            return isinstance(obj, Transcript)
        except ImportError:
            return False

    def build_text(self, obj) -> str:
        parts: list[str] = []
        title = getattr(obj.capture, "title", "") or ""
        if title:
            parts.append(f"Title:\n{title}")
        source_type = getattr(obj.capture, "source_type", "")
        if source_type:
            parts.append(f"Source:\n{source_type}")
        if obj.raw_text:
            parts.append(f"Transcript:\n{obj.raw_text}")
        return "\n\n".join(parts)

    def get_library_id(self, obj) -> UUID:
        author = getattr(obj.capture, "author", None)
        return get_or_create_user_library(author)

    def get_source_path(self, obj) -> str:
        return f"media_capture/transcripts/{obj.pk}.txt"
