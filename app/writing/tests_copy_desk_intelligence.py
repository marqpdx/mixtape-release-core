import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from worksessions import services as worksession_services
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

    def _execute_split(self):
        return self.client.post(
            f"/api/writing/pieces/{self.piece.id}/execute-split",
            {},
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

    def test_autosave_no_suggestion_when_suggest_splits_false(self):
        self.piece.suggest_splits = False
        self.piece.save(update_fields=["suggest_splits", "updated_at"])
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 600)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(SplitSuggestion.objects.filter(piece=self.piece).exists())
        self.assertIsNone(response.data["split_suggestion_status"])
        mocked_queue.assert_not_called()

    def test_autosave_no_suggestion_when_no_target(self):
        self.piece.target_wordcount = None
        self.piece.save(update_fields=["target_wordcount", "updated_at"])
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 600)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(SplitSuggestion.objects.filter(piece=self.piece).exists())
        self.assertIsNone(response.data["split_suggestion_status"])
        mocked_queue.assert_not_called()

    def test_autosave_does_not_duplicate_pending_suggestion(self):
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="pending",
            suggestions=[],
            word_count_at_suggestion=460,
        )
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 600)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(SplitSuggestion.objects.filter(piece=self.piece).count(), 1)
        self.assertEqual(response.data["split_suggestion_status"], "pending")
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

    def test_autosave_returns_current_status_in_response(self):
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[{"after_paragraph_index": 1, "rationale": "Natural pivot"}],
            word_count_at_suggestion=470,
        )
        with patch("writing.tasks.generate_split_suggestion_task.apply_async") as mocked_queue:
            response = self._autosave(_body_json(*(["word"] * 450)))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["split_suggestion_status"], "ready")
        mocked_queue.assert_not_called()

    def test_get_suggestion_returns_none_when_absent(self):
        response = self.client.get(f"/api/writing/pieces/{self.piece.id}/split-suggestion")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": None, "suggestions": []})

    def test_get_suggestion_returns_ready_suggestion(self):
        suggestion = SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[{"after_paragraph_index": 2, "rationale": "Natural pivot"}],
            word_count_at_suggestion=470,
        )
        response = self.client.get(f"/api/writing/pieces/{self.piece.id}/split-suggestion")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(suggestion.id))
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual(response.data["suggestions"], suggestion.suggestions)

    def test_get_excludes_executed_and_declined_suggestions(self):
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="executed",
            suggestions=[{"after_paragraph_index": 1, "rationale": "old"}],
            word_count_at_suggestion=470,
        )
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="declined",
            suggestions=[{"after_paragraph_index": 2, "rationale": "old"}],
            word_count_at_suggestion=471,
        )
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
        self.assertEqual(response.data["status"], "shown")
        self.assertEqual(response.data["suggestions"], suggestion.suggestions)

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

    def test_post_dismiss_transitions_to_dismissed(self):
        suggestion = SplitSuggestion.objects.create(
            piece=self.piece,
            status="ready",
            suggestions=[],
            word_count_at_suggestion=470,
        )
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/split-suggestion",
            {"action": "dismiss"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, "dismissed")
        self.piece.refresh_from_db()
        self.assertTrue(self.piece.suggest_splits)

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

    def test_post_no_actionable_suggestion_returns_404(self):
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="pending",
            suggestions=[],
            word_count_at_suggestion=470,
        )
        response = self.client.post(
            f"/api/writing/pieces/{self.piece.id}/split-suggestion",
            {"action": "view"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_split_creates_session_and_new_piece(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0, marker_title="Part Two")
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        SplitSuggestion.objects.create(
            piece=self.piece,
            status="shown",
            suggestions=[{"after_paragraph_index": 1, "rationale": "Pivot"}],
            word_count_at_suggestion=470,
        )

        response = self._execute_split()

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
        self.assertEqual(str(new_piece.sponsor_object_id), str(self.piece.sponsor_object_id))

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

    def test_execute_split_multiple_markers_creates_multiple_pieces(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", "Part C", split_after=0, marker_title="Part Two")
        self.working_copy.body_json["content"].insert(
            3,
            {
                "type": "splitMarker",
                "attrs": {
                    "markerId": "marker-2",
                    "source": "manual",
                    "title": "Part Three",
                    "rationale": None,
                },
            },
        )
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        response = self._execute_split()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["new_piece_ids"]), 2)
        session = WorkSession.objects.get(pk=response.data["session_id"])
        self.assertEqual(session.items.count(), 2)
        self.assertEqual(list(session.items.order_by("sequence").values_list("sequence", flat=True)), [1, 2])

        titles = list(
            WritingPiece.objects.filter(pk__in=response.data["new_piece_ids"])
            .order_by("created_at")
            .values_list("title", flat=True)
        )
        self.assertEqual(titles, ["Part Two", "Part Three"])

    def test_execute_split_untitled_marker_creates_blank_title(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0, marker_title=None)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        response = self._execute_split()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_piece = WritingPiece.objects.get(pk=response.data["new_piece_ids"][0])
        self.assertEqual(new_piece.title, "")

    def test_execute_split_response_shape(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        response = self._execute_split()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertSetEqual(set(response.data.keys()), {"session_id", "surface_body_json", "new_piece_ids"})
        self.assertEqual(response.data["surface_body_json"]["type"], "doc")
        self.assertEqual(len(response.data["new_piece_ids"]), 1)

    def test_execute_split_new_pieces_inherit_writing_kind(self):
        self.piece.writing_kind = "dispatch"
        self.piece.save(update_fields=["writing_kind", "updated_at"])
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        response = self._execute_split()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_piece = WritingPiece.objects.get(pk=response.data["new_piece_ids"][0])
        self.assertEqual(new_piece.writing_kind, "dispatch")

    def test_execute_split_no_markers_returns_400(self):
        self.working_copy.body_json = _body_json("Only one section")
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        response = self._execute_split()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "No split markers found in working copy.")

    def test_execute_split_no_working_copy_returns_400(self):
        self.working_copy.delete()
        response = self._execute_split()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "No working copy found for this piece.")

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

    def test_execute_split_unauthenticated(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])
        self.client.force_authenticate(user=None)
        response = self._execute_split()
        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

    def test_execute_split_nonexistent_piece_returns_404(self):
        response = self.client.post(
            f"/api/writing/pieces/{uuid.uuid4()}/execute-split",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_work_session_is_active_after_execute(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        response = self._execute_split()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = WorkSession.objects.get(pk=response.data["session_id"])
        self.assertIsNone(session.ended_at)
        self.assertTrue(session.is_active)

    def test_surface_document_roundtrips_segments(self):
        self.working_copy.body_json = _body_json("Part A", "Part B", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        session = execute_split(self.piece, self.author)
        segments = worksession_services._parse_segments(session.surface_document.body_json["content"], session)

        self.assertEqual(len(segments), 2)
        self.assertTrue(segments[0]["is_anchor"])
        self.assertFalse(segments[1]["is_anchor"])
        self.assertEqual(segments[0]["artifact_id"], str(self.piece.pk))
        self.assertEqual(
            segments[1]["artifact_id"],
            str(session.items.order_by("sequence").first().object_id),
        )

    def test_checkpoint_extraction_updates_pieces(self):
        self.working_copy.body_json = _body_json("Anchor original", "Emitted original", split_after=0)
        self.working_copy.save(update_fields=["body_json", "updated_at"])

        session = execute_split(self.piece, self.author)
        emitted_piece = WritingPiece.objects.get(pk=session.items.first().object_id)
        session.surface_document.body_json = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Anchor revised"}]},
                {
                    "type": "segmentBoundary",
                    "attrs": {
                        "artifactType": "writingpiece",
                        "artifactId": str(emitted_piece.pk),
                        "isAnchorReturn": False,
                    },
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "Emitted revised"}]},
            ],
        }
        session.surface_document.save(update_fields=["body_json", "updated_at"])

        extracted = worksession_services.checkpoint_extraction(session)

        self.assertEqual(
            extracted,
            [("writingpiece", str(self.piece.pk)), ("writingpiece", str(emitted_piece.pk))],
        )
        self.working_copy.refresh_from_db()
        self.piece.refresh_from_db()
        emitted_piece.refresh_from_db()
        self.assertEqual(self.working_copy.body_json["content"][0]["content"][0]["text"], "Anchor revised")
        self.assertEqual(self.piece.body_json["content"][0]["content"][0]["text"], "Anchor revised")
        self.assertEqual(emitted_piece.body_json["content"][0]["content"][0]["text"], "Emitted revised")

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
