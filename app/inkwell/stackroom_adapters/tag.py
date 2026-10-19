from __future__ import annotations

from uuid import UUID

from django.conf import settings

from classifications.models import Tag
from stackroom_client import get_or_create_group_library

from .base import BaseStackroomAdapter


class TagAdapter(BaseStackroomAdapter):
    """
    Indexes Idea Tags only (ADR-0058 D7) — Tag.is_idea=True. Ordinary
    platform Tags are not Ideas and are not indexed here; if a future
    consumer needs semantic matching over all Tags, that is a second,
    separate adapter rather than widening this one (Spike Reconnaissance
    Protocol: name the second-consumer trigger before generalizing).
    """

    adapter_name = "tag_idea"

    def supports(self, obj) -> bool:
        return isinstance(obj, Tag) and obj.is_idea

    def build_text(self, tag: Tag) -> str:
        parts: list[str] = [tag.title]
        if tag.summary:
            parts.append(tag.summary)
        return "\n\n".join(parts)

    def get_library_id(self, tag: Tag) -> UUID:
        # Ideas are platform-wide, not owned by one user or Group (D4), so they
        # are indexed under the site's Default Group — the same stand-in for
        # "platform-owned" that D4 uses for Place ownership.
        from groups.models import Group

        default_slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "crossroads")
        group = Group.objects.get(slug=default_slug)
        return get_or_create_group_library(group)

    def get_source_path(self, tag: Tag) -> str:
        return f"classifications/tags/{tag.pk}.txt"
