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
from writing.models import Seed
from writing.tasks import transcribe_seed_task
from groups.models import Group
from publishing.models import ContentPlacement
from writing.models import WritingPiece, WritingVersion


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
        piece = _create_piece(author=self.user, sponsor=self.user)
        group = _create_group(sponsor=self.user)

        publish_response = self._publish(
            piece,
            payload={
                "destinations": {"groups": [str(group.id)]},
                "placement_options": {"visibility": "public"},
            },
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(publish_response.data.get("placements_created", 0), 1)
        piece.refresh_from_db()

        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        updated_body = _body_json("draft changed again")
        piece.body_json = updated_body
        piece.save(update_fields=["body_json", "updated_at"])

        self.client.force_authenticate(user=None)
        placement = ContentPlacement.objects.get(
            source_object_id=piece.id,
            target_object_id=group.id,
            channel="feed",
        )
        self.assertEqual(placement.visibility, "public")
        response = self.client.get(f"/api/groups/{group.slug}/writing/{piece.slug}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["body_json"], version.body_json)
        self.assertNotEqual(response.data["body_json"], updated_body)

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

    @patch("writing.tasks.transcribe_audio", return_value=SimpleNamespace(text="hello transcript"))
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
