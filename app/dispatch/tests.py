from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from dispatch.models import DispatchContent, DispatchOutlineNode
from writing.models import WorkingDocument, WritingPiece


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _create_piece(*, author: User, title: str = "Dispatch Piece", enable_outline: bool = False) -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.username,
        title=title,
        body_json=_body_json("Dispatch content"),
        writing_kind="dispatch",
        status="draft",
        enable_outline=enable_outline,
    )
    piece.set_sponsor(author)
    piece.set_submitted_by(author)
    piece.save()
    return piece


class DispatchOutlineApiTests(TestCase):
    def setUp(self):
        self.u1 = User.objects.create_user(username="u1", email="u1@example.com", password="pass123")
        self.u2 = User.objects.create_user(username="u2", email="u2@example.com", password="pass123")
        self.u3 = User.objects.create_user(username="u3", email="u3@example.com", password="pass123")

        self.piece = _create_piece(author=self.u1, enable_outline=False)
        self.dispatch_content = DispatchContent.objects.create(created_by=self.u1)
        self.dispatch_content.collaborators.add(self.u1)
        self.dispatch_content.collaborators.add(self.u2)
        WorkingDocument.objects.create(
            piece=self.piece,
            user=self.u1,
            body_json=self.piece.body_json,
            title=self.piece.title,
            dispatch_content=self.dispatch_content,
        )

        self.client = APIClient()

    def _outline_url(self, piece_id):
        return f"/api/dispatch/outline/{piece_id}"

    def _create_url(self):
        return "/api/dispatch/outline"

    def _node_url(self, node_id):
        return f"/api/dispatch/outline/node/{node_id}"

    def test_outline_disabled_returns_empty(self):
        self.client.force_authenticate(self.u1)
        response = self.client.get(self._outline_url(self.piece.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_create_blocked_when_outline_disabled(self):
        self.client.force_authenticate(self.u1)
        response = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Intro"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Outline is not enabled", response.data.get("detail", ""))

    def test_create_root_and_child_and_get_tree(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])

        self.client.force_authenticate(self.u1)
        root = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Intro"},
            format="json",
        )
        self.assertEqual(root.status_code, status.HTTP_201_CREATED)
        self.assertEqual(root.data["order_index"], 0)

        child = self.client.post(
            self._create_url(),
            {
                "writing_piece": str(self.piece.id),
                "title": "Detail",
                "parent": root.data["id"],
            },
            format="json",
        )
        self.assertEqual(child.status_code, status.HTTP_201_CREATED)

        tree = self.client.get(self._outline_url(self.piece.id))
        self.assertEqual(tree.status_code, status.HTTP_200_OK)
        self.assertEqual(len(tree.data), 1)
        self.assertEqual(tree.data[0]["title"], "Intro")
        self.assertEqual(len(tree.data[0]["children"]), 1)
        self.assertEqual(tree.data[0]["children"][0]["title"], "Detail")

    def test_parent_must_belong_to_same_piece(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])
        piece_b = _create_piece(author=self.u1, title="Piece B", enable_outline=True)

        self.client.force_authenticate(self.u1)
        parent_b = self.client.post(
            self._create_url(),
            {"writing_piece": str(piece_b.id), "title": "Root B"},
            format="json",
        )
        response = self.client.post(
            self._create_url(),
            {
                "writing_piece": str(self.piece.id),
                "title": "Bad Child",
                "parent": parent_b.data["id"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)

    def test_prevent_self_parent(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])
        self.client.force_authenticate(self.u1)

        root = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Intro"},
            format="json",
        )
        response = self.client.patch(
            self._node_url(root.data["id"]),
            {"parent": root.data["id"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)

    def test_reorder_nodes(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])
        self.client.force_authenticate(self.u1)

        a = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "A"},
            format="json",
        ).data
        b = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "B"},
            format="json",
        ).data

        self.client.patch(self._node_url(a["id"]), {"order_index": 1}, format="json")
        self.client.patch(self._node_url(b["id"]), {"order_index": 0}, format="json")

        tree = self.client.get(self._outline_url(self.piece.id))
        self.assertEqual([n["title"] for n in tree.data], ["B", "A"])

    def test_anchor_update(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])
        self.client.force_authenticate(self.u1)

        node = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "With Anchor", "anchor_target": None},
            format="json",
        )
        self.assertEqual(node.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(node.data["anchor_target"])

        new_anchor = "11111111-1111-1111-1111-111111111111"
        patch = self.client.patch(
            self._node_url(node.data["id"]),
            {"anchor_target": new_anchor},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(patch.data["anchor_target"], new_anchor)

    def test_permissions_collaborator_allowed_non_collaborator_denied(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])

        self.client.force_authenticate(self.u2)
        create_as_collab = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Collab Node"},
            format="json",
        )
        self.assertEqual(create_as_collab.status_code, status.HTTP_201_CREATED)

        node_id = create_as_collab.data["id"]

        self.client.force_authenticate(self.u3)
        denied_get = self.client.get(self._outline_url(self.piece.id))
        denied_create = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Nope"},
            format="json",
        )
        denied_patch = self.client.patch(self._node_url(node_id), {"title": "Nope"}, format="json")
        denied_delete = self.client.delete(self._node_url(node_id))

        self.assertEqual(denied_get.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(denied_create.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(denied_patch.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(denied_delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_node(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])
        self.client.force_authenticate(self.u1)

        node = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "title": "Delete Me"},
            format="json",
        )
        delete_response = self.client.delete(self._node_url(node.data["id"]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DispatchOutlineNode.objects.filter(id=node.data["id"]).exists())

    def test_writing_piece_list_includes_enable_outline(self):
        self.piece.enable_outline = True
        self.piece.save(update_fields=["enable_outline"])

        self.client.force_authenticate(self.u1)
        response = self.client.get("/api/writing/pieces")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data.get("results") if isinstance(response.data, dict) else response.data
        self.assertGreaterEqual(len(payload), 1)
        self.assertIn("enable_outline", payload[0])
