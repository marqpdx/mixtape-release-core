from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from profiles.models import UserProfile
from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library, SourceFile
from stackroom.tasks.processing import process_artifact

from .base import BaseStackroomAdapter


class UserProfileStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "user_profile"

    def supports(self, obj) -> bool:
        return isinstance(obj, UserProfile)

    def build_text(self, profile: UserProfile) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Display Name", profile.display_name)
        append_section("Quick Intro", profile.quick_intro)
        append_section("Right Now", profile.right_now)
        append_section("Skills", profile.skills)
        append_section("Work Areas", profile.work_areas)
        append_section("Practice Area", profile.practice_area)
        append_section("Location", profile.location)

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        text = self.build_text(obj)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_or_create_personal_library(self, profile: UserProfile) -> Library:
        user = profile.user
        user_ct = ContentType.objects.get_for_model(user)
        library = Library.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            is_personal_puddlejump=True,
        ).first()
        if library:
            return library

        library = Library(
            title="My Puddlejump",
            summary="Your canonical archive. The things you stand behind.",
            body=(
                "Puddlejump is intentionally small, intentionally portable, "
                "intentionally human-governed. Files here sync with your filesystem, "
                "can be versioned in git, and are always exportable. Nothing is trapped."
            ),
            is_personal_puddlejump=True,
            puddlejump_origin="created",
            visibility="private",
            scope="general",
        )
        library.set_sponsor(user)
        library.author = user
        library.submitted_by = user
        library.save()
        return library

    def ingest_local(self, obj, sync_state, *, reason: str) -> dict[str, Any]:
        profile = obj
        library = self._get_or_create_personal_library(profile)
        text = self.build_text(profile)
        text_hash = self.current_hash(profile)
        source_path = f"profiles/{profile.user_id}/profile.txt"
        filename = f"profile-{profile.user.username}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=profile.user,
            origin="external",
        )

        # Profile text is mutable. Clear prior derived artifacts before rebuilding.
        source_file.artifacts.all().delete()

        ingestion_run = IngestionRun.objects.create(
            source_file=source_file,
            status="running",
            started_at=timezone.now(),
        )

        artifact = Artifact.objects.create(
            source_file=source_file,
            artifact_uid="user_profile_text",
            artifact_type="profile_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "user_profile",
                "profile_id": str(profile.id),
                "user_id": str(profile.user_id),
                "artifact_id": str(artifact.id),
            },
        )

        process_artifact.delay(
            artifact_id=str(artifact.id),
            model_name="all-mpnet-base-v2",
            model_version="1",
            provider="sentence-transformers",
        )

        return {
            "status": "synced",
            "hash": text_hash,
            "library_id": library.id,
            "source_file_id": source_file.id,
            "artifact_id": artifact.id,
            "metadata": {
                "reason": reason,
                "username": profile.user.username,
                "slug": profile.slug,
                "display_name": profile.display_name,
            },
        }

    def deactivate_local(self, obj, sync_state, *, reason: str) -> dict[str, Any]:
        source_file_id = sync_state.stackroom_source_file_id
        if source_file_id:
            source_file = SourceFile.objects.filter(id=source_file_id).first()
            if source_file:
                source_file.artifacts.all().delete()
        return {
            "status": "deactivated",
            "metadata": {"reason": reason},
        }
