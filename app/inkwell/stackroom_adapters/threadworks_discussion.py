from __future__ import annotations

from uuid import UUID

from stackroom_client import get_or_create_group_library
from threadworks.models import Discussion

from .base import BaseStackroomAdapter


class ThreadworksDiscussionAdapter(BaseStackroomAdapter):
    adapter_name = "threadworks_discussion"

    def supports(self, obj) -> bool:
        return isinstance(obj, Discussion)

    def build_text(self, discussion: Discussion) -> str:
        parts: list[str] = [discussion.title]

        if discussion.description:
            parts.append(discussion.description)

        parts.append("---")

        for post in discussion.posts.filter(is_deleted=False).order_by("created_at"):
            username = post.author.username if post.author else "unknown"
            date_str = post.created_at.date().isoformat()
            parts.append(f"{username} ({date_str}):\n{post.content}")

        return "\n\n".join(parts)

    def get_library_id(self, discussion: Discussion) -> UUID:
        forum = discussion.forum
        sponsor_model = forum.sponsor_content_type.model_class()
        group = sponsor_model.objects.get(pk=forum.sponsor_object_id)
        return get_or_create_group_library(group)

    def get_source_path(self, discussion: Discussion) -> str:
        return f"threadworks/{discussion.forum_id}/{discussion.pk}.txt"
