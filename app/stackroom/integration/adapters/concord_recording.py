from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from concord.models import Recording
from stackroom.models import Artifact, IngestionReceipt, IngestionRun, Library
from stackroom.tasks.processing import process_artifact

from .base import BaseStackroomAdapter


class ConcordRecordingStackroomAdapter(BaseStackroomAdapter):
    adapter_name = "concord_recording"

    def supports(self, obj) -> bool:
        return isinstance(obj, Recording)

    def _latest_transcription(self, recording: Recording):
        return recording.transcriptions.order_by("-version").prefetch_related("segments").first()

    def build_text(self, recording: Recording) -> str:
        sections: list[str] = []

        def append_section(label: str, value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned:
                sections.append(f"{label}:\n{cleaned}")

        append_section("Title", recording.title)
        append_section("Summary", recording.summary)
        append_section("Status", recording.status)
        append_section("Recording ID", str(recording.id))
        if recording.session_id:
            append_section("Session ID", str(recording.session_id))
        if recording.recorded_at:
            append_section("Recorded At", recording.recorded_at.isoformat())

        transcription = self._latest_transcription(recording)
        if transcription:
            append_section("Transcription", transcription.text)

            segment_lines: list[str] = []
            for segment in transcription.segments.all().order_by("segment_index"):
                speaker = segment.speaker_label or "Speaker"
                segment_lines.append(f"{speaker}: {segment.text}")
            if segment_lines:
                sections.append("Transcript Segments:\n" + "\n".join(segment_lines))

        return "\n\n".join(sections).strip()

    def current_hash(self, obj) -> str:
        return hashlib.sha256(self.build_text(obj).encode("utf-8")).hexdigest()

    def _resolve_library_user(self, recording: Recording):
        return recording.author or recording.submitted_by

    def _get_or_create_personal_library(self, recording: Recording) -> Library:
        user = self._resolve_library_user(recording)
        if user is None:
            raise ValueError("Recording must have author or submitted_by for personal library routing")

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
            body="Concord recording text ingested for retrieval.",
            is_personal_puddlejump=True,
            puddlejump_origin="created",
            visibility="private",
            scope="audio",
        )
        library.set_sponsor(user)
        library.author = user
        library.submitted_by = user
        library.save()
        return library

    def ingest_local(self, obj, sync_state, *, reason: str) -> dict[str, Any]:
        recording = obj
        library = self._get_or_create_personal_library(recording)
        text = self.build_text(recording)
        text_hash = self.current_hash(recording)
        owner_id = recording.author_id or recording.submitted_by_id or recording.id
        source_path = f"concord-recordings/{owner_id}/{recording.id}.txt"
        filename = f"concord-recording-{recording.id}.txt"

        source_file = self.get_or_reuse_source_file(
            library=library,
            source_path=source_path,
            filename=filename,
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            hash_sha256=text_hash,
            created_by=recording.submitted_by or recording.author,
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
            artifact_uid=f"concord_recording_text:{recording.id}",
            artifact_type="concord_recording_text",
            format="text/plain",
            text=text,
        )

        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "reason": reason,
                "content_type": "concord_recording",
                "recording_id": str(recording.id),
                "session_id": str(recording.session_id) if recording.session_id else "",
                "status": recording.status,
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
                "recording_id": str(recording.id),
                "session_id": str(recording.session_id) if recording.session_id else "",
                "status": recording.status,
            },
        }
