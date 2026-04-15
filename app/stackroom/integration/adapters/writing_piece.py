from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library, SourceFile
from stackroom.tasks.processing import process_artifact
from utils.writing.writing_utils import extract_text_from_prosemirror
from writing.models import WritingPiece

from .base import BaseStackroomAdapter


class WritingPieceStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "writing_piece"

    def supports(self, obj) -> bool:
        return isinstance(obj, WritingPiece)

    def build_text(self, piece: WritingPiece) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Title", piece.title)
        append_section("Excerpt", piece.excerpt)
        append_section("Body", extract_text_from_prosemirror(piece.body_json or {}))
        append_section("Writing Kind", piece.writing_kind)
        append_section("Status", piece.status)
        append_section("Writing Piece ID", str(piece.id))

        if piece.author_id:
            append_section("Author ID", str(piece.author_id))

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        text = self.build_text(obj)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_or_create_personal_library(self, piece: WritingPiece) -> Library:
        user = piece.author or piece.submitted_by
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
            scope="writing",
        )
        library.set_sponsor(user)
        library.author = user
        library.submitted_by = user
        library.save()
        return library

    def ingest_local(self, obj, sync_state, *, reason: str) -> dict[str, Any]:
        piece = obj
        library = self._get_or_create_personal_library(piece)
        text = self.build_text(piece)
        text_hash = self.current_hash(piece)
        author_id = piece.author_id or piece.submitted_by_id
        source_path = f"writing-pieces/{author_id}/{piece.id}.txt"
        filename = f"writing-piece-{piece.id}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=piece.author or piece.submitted_by,
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
            artifact_uid=f"writing_piece_text:{piece.id}",
            artifact_type="writing_piece_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "writing_piece",
                "writing_piece_id": str(piece.id),
                "writing_kind": piece.writing_kind,
                "status": piece.status,
                "author_id": str(piece.author_id) if piece.author_id else "",
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
                "writing_piece_id": str(piece.id),
                "writing_kind": piece.writing_kind,
                "status": piece.status,
                "author_id": str(piece.author_id) if piece.author_id else "",
            },
        }
