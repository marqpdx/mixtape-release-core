from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from dispatch.models import DispatchCollaborator, DispatchContent
from writing.models import WorkingDocument, WritingPiece


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _create_piece(*, author: User, title: str = "Dispatch with comments") -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.username,
        title=title,
        body_json=_body_json("Dispatch body"),
        writing_kind="dispatch",
        status="draft",
    )
    piece.set_sponsor(author)
    piece.set_submitted_by(author)
    piece.save()
    return piece


class DispatchCommentsApiContractTests(TestCase):
    """
    Contract tests from pre-tests/dispatch-comments-pre.md.
    These intentionally assert expected API behavior for comments endpoints.
    """

    def setUp(self):
        self.author = User.objects.create_user("author", "author@test.com", "pass")
        self.editor_user = User.objects.create_user("editor", "editor@test.com", "pass")
        self.commenter_user = User.objects.create_user("commenter", "commenter@test.com", "pass")
        self.outsider = User.objects.create_user("outsider", "outsider@test.com", "pass")

        self.piece = _create_piece(author=self.author)

        self.dispatch_content = DispatchContent.objects.create(created_by=self.author)
        DispatchCollaborator.objects.create(content=self.dispatch_content, user=self.author, role="editor")
        DispatchCollaborator.objects.create(content=self.dispatch_content, user=self.editor_user, role="editor")
        DispatchCollaborator.objects.create(content=self.dispatch_content, user=self.commenter_user, role="commenter")

        WorkingDocument.objects.create(
            piece=self.piece,
            user=self.author,
            title=self.piece.title,
            body_json=self.piece.body_json,
            dispatch_content=self.dispatch_content,
        )

        self.client = APIClient()

    def _list_url(self):
        return f"/api/dispatch/comments/{self.piece.id}"

    def _create_url(self):
        return "/api/dispatch/comments"

    def _comment_url(self, comment_id):
        return f"/api/dispatch/comments/{comment_id}"

    def _resolve_url(self, comment_id):
        return f"/api/dispatch/comments/{comment_id}/resolve"

    def _unresolve_url(self, comment_id):
        return f"/api/dispatch/comments/{comment_id}/unresolve"

    def _create_comment(self, as_user, body="Root comment"):
        self.client.force_authenticate(as_user)
        return self.client.post(
            self._create_url(),
            {
                "writing_piece": str(self.piece.id),
                "body": body,
                "block_id": "block-1",
                "anchor_from": 0,
                "anchor_to": 4,
                "quoted_text": "Test",
            },
            format="json",
        )

    def test_create_comment_as_author(self):
        response = self._create_comment(self.author)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_comment_as_editor(self):
        response = self._create_comment(self.editor_user)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_comment_as_commenter(self):
        response = self._create_comment(self.commenter_user)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_comment_as_outsider_denied(self):
        response = self._create_comment(self.outsider)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_comment_unauthenticated(self):
        response = self.client.post(
            self._create_url(),
            {"writing_piece": str(self.piece.id), "body": "Hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_comments_as_author_returns_thread_and_counts(self):
        self._create_comment(self.author)
        self.client.force_authenticate(self.author)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("counts", response.data)
        self.assertIn("total", response.data["counts"])

    def test_edit_delete_resolve_flow(self):
        created = self._create_comment(self.author)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        comment_id = created.data["id"]

        self.client.force_authenticate(self.author)
        edit = self.client.patch(self._comment_url(comment_id), {"body": "Edited"}, format="json")
        self.assertEqual(edit.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.editor_user)
        resolve = self.client.post(self._resolve_url(comment_id), {}, format="json")
        self.assertEqual(resolve.status_code, status.HTTP_200_OK)

        unresolve = self.client.post(self._unresolve_url(comment_id), {}, format="json")
        self.assertEqual(unresolve.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.author)
        delete = self.client.delete(self._comment_url(comment_id))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)

    def test_resolve_as_commenter_denied(self):
        created = self._create_comment(self.author)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        comment_id = created.data["id"]

        self.client.force_authenticate(self.commenter_user)
        response = self.client.post(self._resolve_url(comment_id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_comment_on_non_collaborative_piece(self):
        piece2 = _create_piece(author=self.author, title="No DispatchContent")
        self.client.force_authenticate(self.editor_user)
        response = self.client.post(
            self._create_url(),
            {"writing_piece": str(piece2.id), "body": "Should fail"},
            format="json",
        )
        self.assertIn(response.status_code, {status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN})
