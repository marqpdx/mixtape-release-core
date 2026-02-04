from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

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
            payload={"destinations": {"groups": [group.slug]}},
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        version = WritingVersion.objects.get(writing_piece=piece, sequence_no=1)
        updated_body = _body_json("draft changed again")
        piece.body_json = updated_body
        piece.save(update_fields=["body_json", "updated_at"])

        self.client.force_authenticate(user=None)
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
