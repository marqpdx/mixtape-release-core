from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library, SourceFile
from stackroom.tasks.processing import process_artifact
from writing.models import Seed

from .base import BaseStackroomAdapter


class SeedStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "seed"

    def supports(self, obj) -> bool:
        return isinstance(obj, Seed)

    def build_text(self, seed: Seed) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Seed Kind", seed.kind)
        append_section("Status", seed.status)
        append_section("Body", seed.body_text)
        append_section("Transcript", seed.transcript_text)
        append_section("Context URL", seed.context_url)
        append_section("Source", seed.source)

        if seed.audio_file_id:
            append_section("Audio File", str(seed.audio_file_id))

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        text = self.build_text(obj)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_or_create_personal_library(self, seed: Seed) -> Library:
        user = seed.author
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
        seed = obj
        library = self._get_or_create_personal_library(seed)
        text = self.build_text(seed)
        text_hash = self.current_hash(seed)
        source_path = f"seeds/{seed.author_id}/{seed.id}.txt"
        filename = f"seed-{seed.id}.txt"

        source_file = SourceFile.objects.filter(library=library, path=source_path).first()
        if source_file is None:
            source_file = SourceFile.objects.create(
                library=library,
                origin="external",
                path=source_path,
                filename=filename,
                content_type="text/plain",
                size_bytes=len(text.encode("utf-8")),
                hash_sha256=text_hash,
                created_by=seed.author,
            )
        elif source_file.hash_sha256 != text_hash:
            source_file.hash_sha256 = text_hash
            source_file.filename = filename
            source_file.content_type = "text/plain"
            source_file.size_bytes = len(text.encode("utf-8"))
            source_file.created_by = source_file.created_by or seed.author
            source_file.save(
                update_fields=[
                    "hash_sha256",
                    "filename",
                    "content_type",
                    "size_bytes",
                    "created_by",
                    "updated_at",
                ]
            )

        source_file.artifacts.all().delete()

        ingestion_run = IngestionRun.objects.create(
            source_file=source_file,
            status="running",
            started_at=timezone.now(),
        )

        artifact = Artifact.objects.create(
            source_file=source_file,
            artifact_uid=f"seed_text:{seed.id}",
            artifact_type="seed_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "seed",
                "seed_id": str(seed.id),
                "author_id": str(seed.author_id),
                "kind": seed.kind,
                "status": seed.status,
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
                "seed_id": str(seed.id),
                "kind": seed.kind,
                "status": seed.status,
                "author_id": str(seed.author_id),
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
