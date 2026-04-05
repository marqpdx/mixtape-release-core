from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from worksessions.models import WorkSession
from writing.models import SplitSuggestion, WorkingDocument, WritingPiece
from writing.split_service import execute_split


User = get_user_model()


def _body_json(*paragraphs: str, split_after: int | None = None, marker_title: str | None = None) -> dict:
    content = []
    for idx, text in enumerate(paragraphs):
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        )
        if split_after is not None and idx == split_after:
            content.append(
                {
                    "type": "splitMarker",
                    "attrs": {
                        "markerId": f"marker-{idx}",
                        "source": "manual",
                        "title": marker_title,
                        "rationale": None,
                    },
                }
            )
    return {"type": "doc", "content": content}


def _create_piece(*, author: User, sponsor, title: str = "Split Draft") -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.get_full_name() or author.username,
        submitted_by=author,
        title=title,
        excerpt="Draft excerpt",
        body_json=_body_json("alpha"),
        status="draft",
        writing_kind="post",
        target_wordcount=400,
        suggest_splits=True,
    )
    piece.set_sponsor(sponsor)
    piece.slug = f"{title.lower().replace(' ', '-')}-{author.username}"
    piece.save()
    return piece


class CopyDeskIntelligenceTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="copy_author",
            email="copy_author@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="copy_other",
            email="copy_other@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.author)

        self.piece = _create_piece(author=self.author, sponsor=self.author)
        self.working_copy = WorkingDocument.objects.create(
            piece=self.piece,
            user=self.author,
            title=self.piece.title,
            body_json=_body_json(*(["word"] * 460)),
        )

    def _autosave(self, body_json: dict):
        return self.client.put(
            f"/api/writing/pieces/{self.piece.id}/working-copy",
            {"title": self.piece.title, "body_json": body_json, "excerpt": ""},
            format="json",
        )

    def test_autosave_queues_suggestion_when_over_threshold(self):
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 460)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        suggestion = SplitSuggestion.objects.get(piece=self.piece)
        self.assertEqual(suggestion.status, "pending")
        self.assertEqual(response.data["split_suggestion_status"], "pending")
        mocked_queue.assert_called_once()

    def test_autosave_no_suggestion_when_under_threshold(self):
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 450)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(SplitSuggestion.objects.filter(piece=self.piece).exists())
        self.assertIsNone(response.data["split_suggestion_status"])
        mocked_queue.assert_not_called()

    def test_autosave_supersedes_ready_suggestion(self):
        old = SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[{"after_paragraph_index": 1, "rationale": "Split here"}],
            word_count_at_suggestion=460,
        )

        with patch("writing.tasks.generate_split_suggestion_task.apply_async"):
            response = self._autosave(_body_json(*(["word"] * 500)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        old.refresh_from_db()
        self.assertEqual(old.status, "superseded")
        self.assertEqual(
            SplitSuggestion.objects.filter(piece=self.piece).count(),
            2,
        )

    def test_get_suggestion_returns_none_when_absent(self):
        response = self.client.get(f"/api/writing/pieces/{self.piece.id}/split-suggestion")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": None, "suggestions": []})

    def test_post_view_transitions_ready_to_shown(self):
        suggestion = SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[{"after_paragraph_index": 2, "rationale": "Natural pivot"}],
            word_count_at_suggestion=470,
        )
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/split-suggestion",
            {"action": "view"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, "shown")

    def test_post_decline_sets_piece_flag_false(self):
        suggestion = SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[],
            word_count_at_suggestion=470,
        )
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/split-suggestion",
            {"action": "decline"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        suggestion.refresh_from_db()
        self.piece.refresh_from_db()
        self.assertEqual(suggestion.status, "declined")
        self.assertFalse(self.piece.suggest_splits)

    def test_post_invalid_action_rejected(self):
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[],
            word_count_at_suggestion=470,
        )
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/split-suggestion",
            {"action": "accept"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_split_creates_session_and_new_piece(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0, marker_title="Part Two")
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="shown",
            suggestions=[{"after_paragraph_index": 1, "rationale": "Pivot"}],
            word_count_at_suggestion=470,
        )

        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/execute-split",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["new_piece_ids"]), 1)
        session = WorkSession.objects.get(pk=response.data["session_id"])
        self.assertEqual(session.owner, self.author)
        self.assertEqual(session.anchor_content_type, ContentType.objects.get_for_model(WritingPiece))
        self.assertEqual(session.anchor_object_id, self.piece.pk)
        self.assertEqual(session.items.count(), 1)

        new_piece = WritingPiece.objects.get(pk=response.data["new_piece_ids"][0])
        self.assertEqual(new_piece.title, "Part Two")
        self.assertEqual(new_piece.sponsor_content_type, self.piece.sponsor_content_type)
        self.assertEqual(new_piece.sponsor_object_id, self.piece.sponsor_object_id)

        self.working_copy.refresh_from_db()
        self.assertEqual(len(self.working_copy.body_json["content"]), 1)
        self.assertEqual(self.working_copy.body_json["content"][0]["content"][0]["text"], "Part A")
        self.assertTrue(
            any(node["type"] == "segmentBoundary" for node in response.data["surface_body_json"]["content"])
        )
        self.assertEqual(
            SplitSuggestion.objects.get(piece=self.piece).status,
            "executed",
        )

    def test_execute_split_no_markers_returns_400(self):
        self.working_copy.body_json = _body_json("Only one section")
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/execute-split",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "No split markers found in working copy.")

    def test_execute_split_as_other_user_forbidden(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        self.client.force_authenticate(self.other_user)
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/execute-split",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_execute_split_service_multiple_markers_creates_multiple_items(self):
        self.working_copy.body_json = _body_json("A", "B", "C", split_after=0)
        self.working_copy.body_json["content"].insert(
            3,
            {
                "type": "splitMarker",
                "attrs": {
                    "markerId": "marker-2",
                    "source": "manual",
                    "title": "Part C",
                    "rationale": None,
                },
            },
        )
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        session = execute_split(self.piece, self.author)
        self.assertEqual(session.items.count(), 2)
        self.assertEqual(list(session.items.order_by("sequence").values_list("sequence", flat=True)), [1, 2])
