from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from writing.api.views import MAX_SEED_AUDIO_BYTES
from writing.models import Seed, WorkingDocument, WritingAnalysisSession, WritingFidelityReport, WritingSuggestedRevision
from writing.tasks import transcribe_seed_task
from groups.models import Group
from publishing.models import ContentPlacement
from writing.models import WritingPiece, WritingVersion
from dispatch.models import DispatchContent


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _create_piece(*, author: User, sponsor) -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.get_full_name() or author.username,
        title="Draft Title",
        excerpt="Draft excerpt",
        body_json=_body_json("draft body"),
        status="draft",
    )
    piece.set_sponsor(sponsor)
    piece.slug = "draft-title"
    piece.set_submitted_by(author)
    piece.save()
    return piece


def _create_group(*, sponsor: User, slug: str = "publish-group") -> Group:
    group = Group(
        title="Publish Group",
        slug=slug,
        description="Test group",
        group_type="community",
        decorators=[],
        additional_permissions=[],
    )
    group.set_sponsor(sponsor)
    group.set_submitted_by(sponsor)
    group.author = sponsor
    group.author_name = sponsor.get_full_name() or sponsor.username
    group.save()
    return group


class PublishingV1Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="publish_user",
            email="publish@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _publish(self, piece: WritingPiece, payload: dict | None = None):
        data = payload or {"destinations": {"personal": True}}
        return self.client.post(
            f"/api/writing/pieces/{piece.id}/publish",
            data,
            format="json",
        )

    def test_publish_creates_version_and_locked_placement(self):
        piece = _create_piece(author=self.user, sponsor=self.user)

        response = self._publish(piece)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        piece.refresh_from_db()
        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        self.assertEqual(version.version_label, "1")
        self.assertEqual(piece.current_version_no, 1)

        placement = ContentPlacement.objects.get(
            source_object_id=piece.id,
            target_object_id=self.user.id,
            channel="feed",
        )
        self.assertFalse(placement.follow_updates)
        self.assertEqual(placement.locked_artifact_object_id, version.id)
        self.assertEqual(placement.visibility, "public")

    def test_second_publish_increments_sequence(self):
        piece = _create_piece(author=self.user, sponsor=self.user)

        first_response = self._publish(piece)
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)

        second_body = _body_json("second body")
        second_response = self._publish(
            piece,
            payload={
                "body_json": second_body,
                "destinations": {"personal": True},
            },
        )
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        piece.refresh_from_db()
        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=2)
        self.assertEqual(version.version_label, "2")
        self.assertEqual(piece.current_version_no, 2)

    def test_scheduled_publish_sets_visibility(self):
        piece = _create_piece(author=self.user, sponsor=self.user)

        scheduled_for = timezone.now() + timedelta(days=1)
        response = self._publish(
            piece,
            payload={
                "scheduled_for": scheduled_for.isoformat(),
                "destinations": {"personal": True},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        piece.refresh_from_db()
        self.assertEqual(piece.status, "scheduled")
        placement = ContentPlacement.objects.get(
            source_object_id=piece.id,
            target_object_id=self.user.id,
            channel="feed",
        )
        self.assertEqual(placement.visibility, "scheduled")

    def test_public_view_uses_artifact_body_json(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        publish_response = self._publish(piece)
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        updated_body = _body_json("draft changed")
        piece.body_json = updated_body
        piece.save(update_fields=["body_json", "updated_at"])

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/writing/pieces/view/{piece.slug}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["body_json"], version.body_json)
        self.assertNotEqual(response.data["body_json"], updated_body)

    def test_group_view_uses_artifact_body_json(self):
        group = _create_group(sponsor=self.user)
        piece = _create_piece(author=self.user, sponsor=group)

        publish_response = self._publish(piece)
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)
        piece.refresh_from_db()

        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        updated_body = _body_json("draft changed again")
        piece.body_json = updated_body
        piece.save(update_fields=["body_json", "updated_at"])

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/groups/{group.slug}/writing/{piece.slug}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sponsor_placements_list_uses_artifact_payload(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        publish_response = self._publish(piece)
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        updated_body = _body_json("draft changed list")
        piece.body_json = updated_body
        piece.save(update_fields=["body_json", "updated_at"])

        self.client.force_authenticate(user=None)
        response = self.client.get(
            f"/api/writing/placements?sponsor_type=member&sponsor_slug={self.user.username}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data)
        display_body = response.data[0]["display"]["body_json"]
        self.assertEqual(display_body, version.body_json)
        self.assertNotEqual(display_body, updated_body)


class WritingAnalysisExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="analysis_user",
            email="analysis@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_export_creates_session_and_returns_block_payload(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        piece.title = "Analysis Draft"
        piece.body_json = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2, "data-block-id": "heading-1"},
                    "content": [{"type": "text", "text": "Why this matters"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Opening "},
                        {
                            "type": "text",
                            "text": "paragraph",
                            "marks": [{"type": "bold"}],
                        },
                    ],
                },
            ],
        }
        piece.save(update_fields=["title", "body_json", "updated_at"])

        response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/export",
            {"planner_type": "local-llm", "planner_label": "test-planner"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["session"]["planner_type"], "local-llm")
        self.assertEqual(response.data["export"]["piece"]["title"], "Analysis Draft")
        self.assertEqual(response.data["export"]["outline"]["mode"], "detected")
        self.assertEqual(len(response.data["export"]["document"]["blocks"]), 2)
        self.assertEqual(response.data["export"]["document"]["blocks"][0]["block_id"], "heading-1")
        self.assertTrue(response.data["export"]["document"]["blocks"][1]["metadata"]["has_marks"])

        session = WritingAnalysisSession.objects.get(id=response.data["session"]["id"])
        self.assertEqual(session.source_piece_id, piece.id)
        self.assertEqual(session.status, WritingAnalysisSession.Status.EXPORTED)
        self.assertEqual(session.export_payload["piece"]["title"], "Analysis Draft")

    def test_export_prefers_working_document_content(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        piece.title = "Piece Title"
        piece.excerpt = "Piece excerpt"
        piece.body_json = _body_json("piece body")
        piece.save(update_fields=["title", "excerpt", "body_json", "updated_at"])

        WorkingDocument.objects.create(
            piece=piece,
            user=self.user,
            title="Working Title",
            excerpt="Working excerpt",
            body_json=_body_json("working body"),
        )

        response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/export",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["export"]["piece"]["title"], "Working Title")
        self.assertEqual(response.data["export"]["piece"]["excerpt"], "Working excerpt")
        self.assertEqual(
            response.data["export"]["document"]["blocks"][0]["text"],
            "working body",
        )
        self.assertEqual(response.data["export"]["source"]["source_kind"], "working_document")

    def test_create_suggested_revision_creates_sibling_draft_and_lineage(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        piece.title = "Original Draft"
        piece.excerpt = "Original excerpt"
        piece.body_json = _body_json("source body")
        piece.save(update_fields=["title", "excerpt", "body_json", "updated_at"])

        export_response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/export",
            {},
            format="json",
        )
        self.assertEqual(export_response.status_code, status.HTTP_201_CREATED)
        session_id = export_response.data["session"]["id"]

        create_response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/sessions/{session_id}/create-revision",
            {},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["piece"]["title"], "Original Draft - Suggested Revision")

        piece.refresh_from_db()
        self.assertEqual(piece.title, "Original Draft")
        self.assertEqual(
            piece.body_json["content"][0]["content"][0]["text"],
            "source body",
        )

        revision = WritingSuggestedRevision.objects.get(id=create_response.data["suggested_revision"]["id"])
        suggested_piece = revision.suggested_piece
        report = WritingFidelityReport.objects.get(suggested_revision=revision)
        self.assertEqual(revision.source_piece_id, piece.id)
        self.assertEqual(str(revision.analysis_session_id), session_id)
        self.assertEqual(suggested_piece.title, "Original Draft - Suggested Revision")
        self.assertEqual(suggested_piece.author_id, piece.author_id)
        self.assertEqual(
            suggested_piece.body_json["content"][0]["content"][0]["text"],
            "source body",
        )
        self.assertTrue(WorkingDocument.objects.filter(piece=suggested_piece, user=self.user).exists())
        self.assertEqual(report.source_piece_id, piece.id)
        self.assertEqual(report.suggested_piece_id, suggested_piece.id)
        self.assertEqual(report.report_payload["summary"]["unchanged_block_count"], 1)
        self.assertEqual(report.report_payload["summary"]["edited_block_count"], 0)
        self.assertEqual(create_response.data["fidelity_report"]["id"], str(report.id))

    def test_create_suggested_revision_is_idempotent_per_session(self):
        piece = _create_piece(author=self.user, sponsor=self.user)
        export_response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/export",
            {},
            format="json",
        )
        self.assertEqual(export_response.status_code, status.HTTP_201_CREATED)
        session_id = export_response.data["session"]["id"]

        first_response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/sessions/{session_id}/create-revision",
            {},
            format="json",
        )
        second_response = self.client.post(
            f"/api/writing/pieces/{piece.id}/analysis/sessions/{session_id}/create-revision",
            {},
            format="json",
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            first_response.data["suggested_revision"]["id"],
            second_response.data["suggested_revision"]["id"],
        )
        self.assertEqual(
            first_response.data["fidelity_report"]["id"],
            second_response.data["fidelity_report"]["id"],
        )


class WritingPdfExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pdf_user",
            email="pdf@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            username="pdf_other",
            email="pdf-other@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("writing.pdf_export.generate_pdf_bytes", return_value=b"%PDF-test")
    def test_pdf_export_prefers_working_document_content(self, mock_pdf):
        piece = _create_piece(author=self.user, sponsor=self.user)
        WorkingDocument.objects.create(
            piece=piece,
            user=self.user,
            title="Working Title",
            excerpt="Working excerpt",
            body_json=_body_json("working body"),
        )

        response = self.client.get(f"/api/writing/pieces/{piece.id}/export/pdf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["X-Export-Source-Kind"], "working_document")
        self.assertIn('working-title.pdf', response["Content-Disposition"])
        self.assertEqual(response.content, b"%PDF-test")
        html = mock_pdf.call_args.kwargs["html"]
        self.assertIn("Working Title", html)
        self.assertIn("Working excerpt", html)
        self.assertIn("working body", html)

    @patch("writing.pdf_export.generate_pdf_bytes", return_value=b"%PDF-dispatch")
    def test_pdf_export_prefers_dispatch_snapshot_when_collaborative(self, mock_pdf):
        piece = _create_piece(author=self.user, sponsor=self.user)
        dispatch_content = DispatchContent.objects.create(
            created_by=self.user,
            content_snapshot=_body_json("dispatch body"),
        )
        WorkingDocument.objects.create(
            piece=piece,
            user=self.user,
            title="Dispatch Title",
            excerpt="Dispatch excerpt",
            body_json=_body_json("working body"),
            dispatch_content=dispatch_content,
        )

        response = self.client.get(f"/api/writing/pieces/{piece.id}/export/pdf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Export-Source-Kind"], "dispatch_content")
        html = mock_pdf.call_args.kwargs["html"]
        self.assertIn("dispatch body", html)
        self.assertNotIn("working body", html)

    @patch("writing.pdf_export.generate_pdf_bytes", return_value=b"%PDF-collab")
    def test_pdf_export_allows_collaborator_via_piece_permission(self, mock_pdf):
        piece = _create_piece(author=self.user, sponsor=self.user)
        dispatch_content = DispatchContent.objects.create(
            created_by=self.user,
            content_snapshot=_body_json("collab body"),
        )
        dispatch_content.collaborators.add(self.other)
        WorkingDocument.objects.create(
            piece=piece,
            user=self.user,
            title="Shared Draft",
            body_json=_body_json("author working body"),
            dispatch_content=dispatch_content,
        )

        self.client.force_authenticate(user=self.other)
        response = self.client.get(f"/api/writing/pieces/{piece.id}/export/pdf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Export-Source-Kind"], "dispatch_content")
        html = mock_pdf.call_args.kwargs["html"]
        self.assertIn("collab body", html)



class VoiceSeedsV1Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="seed_user",
            email="seed@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _voice_file(self, *, name="voice.webm", size=128, content_type="audio/webm"):
        return SimpleUploadedFile(name, b"a" * size, content_type=content_type)

    @patch("writing.api.views.transcribe_seed_task.delay")
    @patch("writing.api.views.default_storage.save", return_value="seeds/audio/test/voice.webm")
    def test_create_voice_seed_multipart(self, _save_mock, delay_mock):
        response = self.client.post(
            "/api/writing/seeds",
            {
                "audio_file": self._voice_file(),
                "kind": "voice",
                "source": "web",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["kind"], "voice")
        self.assertEqual(response.data["status"], "processing")
        self.assertIsNotNone(response.data.get("audio_file"))
        self.assertTrue(response.data.get("audio_url"))
        delay_mock.assert_called_once()

    def test_reject_oversize_file(self):
        response = self.client.post(
            "/api/writing/seeds",
            {
                "audio_file": self._voice_file(size=MAX_SEED_AUDIO_BYTES + 1),
                "source": "web",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertIn("Audio file too large", response.data.get("detail", ""))

    def test_reject_non_audio(self):
        response = self.client.post(
            "/api/writing/seeds",
            {
                "audio_file": self._voice_file(name="bad.txt", content_type="text/plain"),
                "source": "web",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported audio type", response.data.get("detail", ""))

    @patch(
        "writing.tasks.transcribe_audio",
        return_value=SimpleNamespace(
            text="hello transcript",
            backend="whisper",
            model_name="mock-whisper-model",
        ),
    )
    @patch("writing.api.views.transcribe_seed_task.delay")
    @patch("writing.api.views.default_storage.save", return_value="seeds/audio/test/ready.webm")
    def test_transcription_processing_to_ready(self, _save_mock, _delay_mock, _transcribe_mock):
        create = self.client.post(
            "/api/writing/seeds",
            {"audio_file": self._voice_file(), "source": "web"},
            format="multipart",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        seed_id = create.data["id"]

        result = transcribe_seed_task.run(seed_id)
        self.assertEqual(result["status"], "ok")

        detail = self.client.get(f"/api/writing/seeds/{seed_id}")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["status"], "ready")
        self.assertEqual(detail.data["transcript_text"], "hello transcript")
        self.assertEqual(detail.data["body_text"], "hello transcript")
        self.assertEqual(detail.data["transcript_provider"], "whisper")
        self.assertIsNotNone(detail.data["transcript_created_at"])

    @patch("writing.tasks.transcribe_audio", side_effect=RuntimeError("decode failed"))
    @patch("writing.api.views.transcribe_seed_task.delay")
    @patch("writing.api.views.default_storage.save", return_value="seeds/audio/test/fail.webm")
    def test_transcription_failure_sets_failed_state(self, _save_mock, _delay_mock, _transcribe_mock):
        create = self.client.post(
            "/api/writing/seeds",
            {"audio_file": self._voice_file(), "source": "web"},
            format="multipart",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        seed_id = create.data["id"]

        # Run task body once without Celery retry loop.
        try:
            transcribe_seed_task.run(seed_id)
        except Exception:
            pass

        seed = Seed.objects.get(id=seed_id)
        self.assertEqual(seed.status, "failed")
        self.assertIn("decode failed", seed.transcript_error or "")

    @patch("writing.api.views.transcribe_seed_task.delay")
    @patch("writing.api.views.default_storage.save", return_value="seeds/audio/test/list.webm")
    def test_voice_seed_appears_in_list_with_empty_body(self, _save_mock, _delay_mock):
        create = self.client.post(
            "/api/writing/seeds",
            {"audio_file": self._voice_file(), "source": "web"},
            format="multipart",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        seed_id = create.data["id"]

        listing = self.client.get("/api/writing/seeds")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in listing.data}
        self.assertIn(seed_id, ids)

    @patch("writing.api.views.transcribe_seed_task.delay")
    @patch("writing.api.views.default_storage.save", return_value="seeds/audio/test/mixed.webm")
    def test_mixed_list_includes_voice_and_text_seed(self, _save_mock, _delay_mock):
        voice = self.client.post(
            "/api/writing/seeds",
            {"audio_file": self._voice_file(), "source": "web"},
            format="multipart",
        )
        self.assertEqual(voice.status_code, status.HTTP_201_CREATED)

        text = self.client.post(
            "/api/writing/seeds",
            {"body_text": "typed seed"},
            format="json",
        )
        self.assertEqual(text.status_code, status.HTTP_201_CREATED)

        listing = self.client.get("/api/writing/seeds")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        kinds = {item["kind"] for item in listing.data}
        self.assertIn("voice", kinds)
        self.assertIn("text", kinds)

    def test_text_seed_create_still_works(self):
        response = self.client.post(
            "/api/writing/seeds",
            {"body_text": "plain text seed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["kind"], "text")
        self.assertEqual(response.data["status"], "ready")
