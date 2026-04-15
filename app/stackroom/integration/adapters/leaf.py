from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library, SourceFile
from stackroom.tasks.processing import process_artifact
from writing.models import Leaf

from .base import BaseStackroomAdapter


class LeafStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "leaf"

    def supports(self, obj) -> bool:
        return isinstance(obj, Leaf)

    def build_text(self, leaf: Leaf) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Leaf Kind", leaf.kind)
        append_section("Visibility", leaf.visibility)
        append_section("Publish State", "published" if leaf.published_at else "draft")
        append_section("Body", leaf.body_text)
        append_section("Caption", leaf.caption)
        append_section("Link URL", leaf.link_url)

        if leaf.is_reference:
            append_section("Reference Type", leaf.source_content_type.model if leaf.source_content_type else "")
            append_section("Reference ID", str(leaf.source_object_id) if leaf.source_object_id else "")

        if leaf.audio_file_id:
            append_section("Audio File", str(leaf.audio_file_id))
        if leaf.image_file_id:
            append_section("Image File", str(leaf.image_file_id))

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        text = self.build_text(obj)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_or_create_personal_library(self, leaf: Leaf) -> Library:
        user = leaf.author
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
        leaf = obj
        library = self._get_or_create_personal_library(leaf)
        text = self.build_text(leaf)
        text_hash = self.current_hash(leaf)
        source_path = f"leaves/{leaf.author_id}/{leaf.id}.txt"
        filename = f"leaf-{leaf.id}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=leaf.author,
            origin="external",
        )

        source_file.artifacts.all().delete()

        ingestion_run = IngestionRun.objects.create(
            source_file=source_file,
            status="running",
            started_at=timezone.now(),
        )

        artifact = Artifact.objects.create(
            source_file=source_file,
            artifact_uid=f"leaf_text:{leaf.id}",
            artifact_type="leaf_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "leaf",
                "leaf_id": str(leaf.id),
                "author_id": str(leaf.author_id),
                "kind": leaf.kind,
                "visibility": leaf.visibility,
                "published": bool(leaf.published_at),
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
                "leaf_id": str(leaf.id),
                "kind": leaf.kind,
                "visibility": leaf.visibility,
                "published": bool(leaf.published_at),
                "author_id": str(leaf.author_id),
                "is_reference": leaf.is_reference,
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
