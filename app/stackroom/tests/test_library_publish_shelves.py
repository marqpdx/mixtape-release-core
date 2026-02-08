from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from publishing.models import ContentPlacement
from stackroom.models import Library
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


def _create_piece(*, author: User) -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.get_full_name() or author.username,
        title="Draft Title",
        excerpt="Draft excerpt",
        body_json=_body_json("draft body"),
        status="draft",
    )
    piece.set_sponsor(author)
    piece.set_submitted_by(author)
    piece.save()
    return piece


class PublishLibraryShelfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="library_user",
            email="library@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_library(self, *, name: str, visibility: str = "public") -> dict:
        response = self.client.post(
            "/api/stackroom/libraries",
            {
                "tenant_type": "user",
                "tenant_id": str(self.user.id),
                "name": name,
                "scope": "writing",
                "visibility": visibility,
                "summary": "Shelf summary",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _publish(self, piece: WritingPiece, payload: dict) -> dict:
        response = self.client.post(
            f"/api/writing/pieces/{piece.id}/publish",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_publish_just_me_creates_no_placement(self):
        piece = _create_piece(author=self.user)
        data = self._publish(piece, {"audience": "just_me"})

        piece.refresh_from_db()
        self.assertEqual(piece.status, "published")
        self.assertEqual(data.get("placements_created"), 0)
        self.assertIsNone(data.get("publication_group_id"))
        self.assertEqual(ContentPlacement.objects.filter(source_object_id=piece.id).count(), 0)
        self.assertTrue(WritingVersion.objects.filter(writing_piece=piece, sequence_no=1).exists())

    def test_publish_with_shelf_creates_shelf_placement(self):
        library = self._create_library(name="My Writing", visibility="public")
        piece = _create_piece(author=self.user)

        self._publish(
            piece,
            {
                "audience": "readers",
                "destinations": {"shelves": [library["id"]]},
            },
        )

        ct_library = ContentType.objects.get_for_model(Library)
        placement = ContentPlacement.objects.get(
            source_object_id=piece.id,
            target_content_type=ct_library,
            target_object_id=library["id"],
            channel="shelf",
        )
        self.assertEqual(placement.visibility, "public")

    def test_public_library_list_only_returns_public(self):
        public_library = self._create_library(name="Public Shelf", visibility="public")
        self._create_library(name="Members Shelf", visibility="members")

        self.client.force_authenticate(user=None)
        response = self.client.get(
            f"/api/stackroom/libraries/public?username={self.user.username}&scope=writing"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {item["slug"] for item in response.data}
        self.assertIn(public_library["slug"], slugs)
        self.assertEqual(len(response.data), 1)
        sample = response.data[0]
        for key in ("title", "slug", "summary", "visibility", "scope"):
            self.assertIn(key, sample)

    def test_members_shelf_hidden_for_anonymous(self):
        library = self._create_library(name="Members Shelf", visibility="members")
        piece = _create_piece(author=self.user)
        self._publish(
            piece,
            {
                "audience": "readers",
                "destinations": {"shelves": [library["id"]]},
            },
        )

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/stackroom/libraries/{library['id']}/placements")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_library_placements_order_by_published_at(self):
        library = self._create_library(name="Ordered Shelf", visibility="public")

        piece_old = _create_piece(author=self.user)
        self._publish(
            piece_old,
            {
                "audience": "readers",
                "destinations": {"shelves": [library["id"]]},
            },
        )
        piece_old.published_at = timezone.now() - timedelta(days=2)
        piece_old.save(update_fields=["published_at", "updated_at"])

        piece_new = _create_piece(author=self.user)
        self._publish(
            piece_new,
            {
                "audience": "readers",
                "destinations": {"shelves": [library["id"]]},
            },
        )
        piece_new.published_at = timezone.now() - timedelta(hours=1)
        piece_new.save(update_fields=["published_at", "updated_at"])

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/stackroom/libraries/{library['id']}/placements")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 2)

        returned_ids = [item["piece_id"] for item in response.data]
        self.assertEqual(returned_ids[0], str(piece_new.id))
        self.assertEqual(returned_ids[1], str(piece_old.id))
