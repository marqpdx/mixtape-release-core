from __future__ import annotations

from uuid import UUID

from stackroom_client import get_or_create_user_library
from commons.models import Leaf

from .base import BaseStackroomAdapter


class LeafAdapter(BaseStackroomAdapter):
    adapter_name = "leaf"

    def supports(self, obj) -> bool:
        return isinstance(obj, Leaf)

    def build_text(self, leaf: Leaf) -> str:
        parts: list[str] = []

        def add(label: str, value) -> None:
            v = (value or "").strip()
            if v:
                parts.append(f"{label}:\n{v}")

        add("Kind", leaf.kind)
        add("Visibility", leaf.visibility)
        add("Body", leaf.body_text)
        add("Caption", getattr(leaf, "caption", None))
        add("Link URL", getattr(leaf, "link_url", None))
        return "\n\n".join(parts)

    def get_library_id(self, leaf: Leaf) -> UUID:
        return get_or_create_user_library(leaf.author)

    def get_source_path(self, leaf: Leaf) -> str:
        return f"leaves/{leaf.author_id}/{leaf.pk}.txt"
