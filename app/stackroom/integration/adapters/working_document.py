from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library, SourceFile
from stackroom.tasks.processing import process_artifact
from utils.writing.writing_utils import extract_text_from_prosemirror
from writing.models import WorkingDocument

from .base import BaseStackroomAdapter


class WorkingDocumentStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "working_document"

    def supports(self, obj) -> bool:
        return isinstance(obj, WorkingDocument)

    def build_text(self, working_document: WorkingDocument) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Title", working_document.title)
        append_section("Excerpt", working_document.excerpt)
        append_section("Body", extract_text_from_prosemirror(working_document.body_json or {}))
        append_section("Piece ID", str(working_document.piece_id))
        append_section("User ID", str(working_document.user_id))

        if working_document.dispatch_content_id:
            append_section("Dispatch Content ID", str(working_document.dispatch_content_id))

        workflow_states = ", ".join(working_document.workflow_states)
        append_section("Workflow States", workflow_states)

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        text = self.build_text(obj)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_or_create_personal_library(self, working_document: WorkingDocument) -> Library:
        user = working_document.user
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
        working_document = obj
        library = self._get_or_create_personal_library(working_document)
        text = self.build_text(working_document)
        text_hash = self.current_hash(working_document)
        source_path = f"working-documents/{working_document.user_id}/{working_document.id}.txt"
        filename = f"working-document-{working_document.id}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=working_document.user,
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
            artifact_uid=f"working_document_text:{working_document.id}",
            artifact_type="working_document_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "working_document",
                "working_document_id": str(working_document.id),
                "piece_id": str(working_document.piece_id),
                "user_id": str(working_document.user_id),
                "dispatch_content_id": (
                    str(working_document.dispatch_content_id)
                    if working_document.dispatch_content_id
                    else ""
                ),
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
                "working_document_id": str(working_document.id),
                "piece_id": str(working_document.piece_id),
                "user_id": str(working_document.user_id),
                "dispatch_content_id": (
                    str(working_document.dispatch_content_id)
                    if working_document.dispatch_content_id
                    else ""
                ),
                "workflow_states": working_document.workflow_states,
            },
        }
