from __future__ import annotations

import hashlib
from typing import Any

from django.utils import timezone

from curation.models import Collection
from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library
from stackroom.tasks.processing import process_artifact

from .base import BaseStackroomAdapter


class CollectionStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "collection"

    def supports(self, obj) -> bool:
        return isinstance(obj, Collection)

    def build_text(self, collection: Collection) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Title", collection.title)
        append_section("Summary", collection.summary)
        append_section("Body", collection.body)
        append_section("Scope", collection.scope)
        append_section("Visibility", collection.visibility)
        append_section(
            "Sponsor",
            f"{collection.sponsor_content_type.model}:{collection.sponsor_object_id}"
            if collection.sponsor_content_type and collection.sponsor_object_id
            else "",
        )
        append_section("Item Count", str(collection.items.count()))

        item_lines: list[str] = []
        for item in collection.items.order_by("order_index"):
            content_type = item.content_type.model if item.content_type else "source_file"
            parts = [
                f"index={item.order_index}",
                f"type={content_type}",
                f"object_id={item.content_object_id or ''}",
            ]
            if item.title:
                parts.append(f"title={item.title}")
            if item.section_title:
                parts.append(f"section={item.section_title}")
            if item.folder_path:
                parts.append(f"folder={item.folder_path}")
            if item.is_featured:
                parts.append("featured=true")
            if item.notes:
                parts.append(f"notes={item.notes.strip()}")
            item_lines.append(" | ".join(parts))

        if item_lines:
            sections.append("Items:\n" + "\n".join(item_lines))

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        return hashlib.sha256(self.build_text(obj).encode("utf-8")).hexdigest()

    def _get_or_create_sponsor_library(self, collection: Collection) -> Library:
        sponsor = collection.sponsor
        if sponsor is None:
            raise ValueError("Collection sponsor could not be resolved")

        library = Library.objects.filter(
            sponsor_content_type=collection.sponsor_content_type,
            sponsor_object_id=str(collection.sponsor_object_id),
            scope="general",
            visibility="private",
        ).order_by("-created_at").first()
        if library:
            return library

        library = Library(
            title=f"{collection.title or 'Collection'} IR",
            summary="Sponsor-scoped curation library backing Collection IR ingestion.",
            body="Django-native Collection content ingested for retrieval.",
            is_personal_puddlejump=False,
            puddlejump_origin="imported",
            visibility="private",
            scope="general",
        )
        library.set_sponsor(sponsor)
        library.author = collection.author or collection.submitted_by
        library.submitted_by = collection.submitted_by
        library.save()
        return library

    def ingest_local(self, obj, sync_state, *, reason: str) -> dict[str, Any]:
        collection = obj
        library = self._get_or_create_sponsor_library(collection)
        text = self.build_text(collection)
        text_hash = self.current_hash(collection)
        source_path = f"collections/{collection.sponsor_object_id}/{collection.id}.txt"
        filename = f"collection-{collection.id}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=collection.submitted_by or collection.author,
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
            artifact_uid=f"collection_text:{collection.id}",
            artifact_type="collection_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "collection",
                "collection_id": str(collection.id),
                "scope": collection.scope,
                "visibility": collection.visibility,
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
                "collection_id": str(collection.id),
                "scope": collection.scope,
                "visibility": collection.visibility,
                "item_count": collection.items.count(),
            },
        }
