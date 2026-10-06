from __future__ import annotations

from uuid import UUID

from stackroom_client import get_or_create_user_library
from profiles.models import UserProfile

from .base import BaseStackroomAdapter


class UserProfileAdapter(BaseStackroomAdapter):
    adapter_name = "user_profile"

    def supports(self, obj) -> bool:
        return isinstance(obj, UserProfile)

    def build_text(self, profile: UserProfile) -> str:
        parts: list[str] = []

        def add(label: str, value) -> None:
            v = (value or "").strip()
            if v:
                parts.append(f"{label}:\n{v}")

        add("Display Name", profile.display_name)
        add("Quick Intro", profile.quick_intro)
        add("Skills", profile.skills)
        add("Work Areas", profile.work_areas)
        add("Bio", profile.bio_markdown)
        return "\n\n".join(parts)

    def get_library_id(self, profile: UserProfile) -> UUID:
        return get_or_create_user_library(profile.user)

    def get_source_path(self, profile: UserProfile) -> str:
        return f"profiles/{profile.user_id}/{profile.pk}.txt"
