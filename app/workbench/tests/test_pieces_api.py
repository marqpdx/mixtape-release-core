from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from fundamentals.models import MillDraftStatus
from workbench.models import WorkingItemMembership

from .helpers import (
    add_group_member,
    create_feedback,
    create_group,
    create_leaf,
    create_milldraft,
    create_seed,
    create_working_document,
    create_working_item,
    create_writing_piece,
)


User = get_user_model()


class UnifiedPiecesAPITests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="pieces_super",
            email="pieces_super@example.com",
            password="testpass123",
        )
        self.group_admin = User.objects.create_user(
            username="pieces_admin",
            email="pieces_admin@example.com",
            password="testpass123",
        )
        self.non_member = User.objects.create_user(
            username="pieces_other",
            email="pieces_other@example.com",
            password="testpass123",
        )

        self.group = create_group(
            sponsor_user=self.superuser,
            title="Pieces Group",
            slug="pieces-group",
        )
        add_group_member(group=self.group, user=self.group_admin, roles=["admin"])

        self.seed = create_seed(author=self.group_admin, body_text="seed keyword alpha")
        self.leaf = create_leaf(author=self.group_admin, body_text="leaf keyword beta")
        self.milldraft = create_milldraft(
            author=self.group_admin,
            sponsor=self.group,
            title="Mill keyword",
            grist_body="mill body gamma",
            status=MillDraftStatus.CANDIDATE,
        )
        self.promoted_milldraft = create_milldraft(
            author=self.group_admin,
            sponsor=self.group,
            title="Promoted Mill",
            grist_body="should not show",
            status=MillDraftStatus.PROMOTED,
        )
        self.feedback = create_feedback(user=self.group_admin, message="feedback keyword delta")
        self.piece = create_writing_piece(
            author=self.group_admin,
            sponsor=self.group,
            title="Draft Piece",
            status="draft",
        )
        self.working_doc = create_working_document(
            user=self.group_admin,
            piece=self.piece,
            title="Draft keyword",
            text="working doc epsilon",
        )
        self.outsider_seed = create_seed(author=self.non_member, body_text="outsider hidden")

    def _auth_superuser(self):
        self.client.force_authenticate(self.superuser)

    def _endpoint(self, query: str = "") -> str:
        base = f"/api/groups/{self.group.slug}/workbench/pieces"
        return f"{base}?{query}" if query else base

    def test_pieces_returns_supported_types_and_excludes_promoted_milldrafts(self):
        self._auth_superuser()
        response = self.client.get(self._endpoint())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        type_labels = {item["type_label"] for item in response.data}
        self.assertIn("seed", type_labels)
        self.assertIn("leaf", type_labels)
        self.assertIn("milldraft", type_labels)
        self.assertIn("feedback", type_labels)
        self.assertIn("working_document", type_labels)

        titles = {item["title"] for item in response.data}
        self.assertNotIn("Promoted Mill", titles)

    def test_pieces_filter_by_type_seed(self):
        self._auth_superuser()
        response = self.client.get(self._endpoint("type=seed"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data)
        self.assertEqual({item["type_label"] for item in response.data}, {"seed"})

    def test_pieces_search_query_filters_results(self):
        self._auth_superuser()
        response = self.client.get(self._endpoint("q=gamma"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type_label"], "milldraft")

    def test_pieces_ungrouped_filter_excludes_grouped_pieces(self):
        self._auth_superuser()
        item = create_working_item(group=self.group, author=self.superuser, title="Grouped")
        WorkingItemMembership.objects.create(
            working_item=item,
            piece_content_type=ContentType.objects.get_for_model(self.seed),
            piece_object_id=self.seed.id,
            content_snapshot="seed keyword alpha",
            position=0,
        )
        response = self.client.get(self._endpoint("ungrouped=true&type=seed"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertNotIn(str(self.seed.id), ids)

    def test_pieces_include_working_item_references(self):
        self._auth_superuser()
        item = create_working_item(group=self.group, author=self.superuser, title="Grouped")
        WorkingItemMembership.objects.create(
            working_item=item,
            piece_content_type=ContentType.objects.get_for_model(self.seed),
            piece_object_id=self.seed.id,
            content_snapshot="seed keyword alpha",
            position=0,
        )
        response = self.client.get(self._endpoint("type=seed"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seed_row = next(row for row in response.data if row["id"] == str(self.seed.id))
        self.assertEqual(seed_row["working_item_references"][0]["id"], str(item.id))

    def test_pieces_seed_scope_is_group_members_only(self):
        self._auth_superuser()
        response = self.client.get(self._endpoint("type=seed"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.seed.id), ids)
        self.assertNotIn(str(self.outsider_seed.id), ids)

    def test_pieces_non_superuser_rejected(self):
        self.client.force_authenticate(self.group_admin)
        response = self.client.get(self._endpoint())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
