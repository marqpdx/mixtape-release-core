from __future__ import annotations

from uuid import UUID

from stackroom_client import get_or_create_user_library
from writing.models import Seed

from .base import BaseStackroomAdapter


class SeedAdapter(BaseStackroomAdapter):
    adapter_name = "seed"

    def supports(self, obj) -> bool:
        return isinstance(obj, Seed)

    def build_text(self, seed: Seed) -> str:
        parts: list[str] = []

        def add(label: str, value) -> None:
            v = (value or "").strip()
            if v:
                parts.append(f"{label}:\n{v}")

        add("Kind", seed.kind)
        add("Body", seed.body_text)
        add("Transcript", getattr(seed, "transcript_text", None))
        add("Context URL", getattr(seed, "context_url", None))
        return "\n\n".join(parts)

    def get_library_id(self, seed: Seed) -> UUID:
        return get_or_create_user_library(seed.author)

    def get_source_path(self, seed: Seed) -> str:
        return f"seeds/{seed.author_id}/{seed.pk}.txt"
