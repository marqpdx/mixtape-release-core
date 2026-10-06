from __future__ import annotations

from uuid import UUID

from drop.models import Drop
from stackroom_client import get_or_create_group_library, get_or_create_user_library

from .base import BaseStackroomAdapter


class DropAdapter(BaseStackroomAdapter):
    adapter_name = "drop"

    def supports(self, obj) -> bool:
        return isinstance(obj, Drop)

    def build_text(self, drop: Drop) -> str:
        parts: list[str] = [f"@{drop.handle}"]
        parts.append(drop.content)
        if drop.event_date:
            parts.append(f"Date: {drop.event_date.strftime('%A, %B %d %Y')}")
        if drop.related_handle:
            parts.append(f"Related: {drop.related_handle}")
        parts.append(f"Weight: {drop.weight}")
        return "\n\n".join(parts)

    def get_library_id(self, drop: Drop) -> UUID:
        if drop.content_type and drop.content_type.model == "group":
            group = drop.content_type.model_class().objects.get(pk=drop.object_id)
            return get_or_create_group_library(group)
        user = getattr(drop, "created_by", None)
        return get_or_create_user_library(user)

    def get_source_path(self, drop: Drop) -> str:
        if drop.content_type and drop.content_type.model == "group":
            return f"drops/groups/{drop.object_id}/{drop.pk}.txt"
        return f"drops/{drop.pk}.txt"
