from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from writing.models import WorkingDocument, WritingPiece


class WorkingDocumentPreviewTests(TestCase):
    def test_drafts_list_returns_first_two_nonempty_paragraphs(self):
        user = get_user_model().objects.create_user(
            username="preview_editor", email="preview@example.com", password="testpass123"
        )
        piece = WritingPiece(
            author=user,
            author_name="Preview Editor",
            title="Opening Notes",
            status="draft",
            body_json={
                "type": "doc",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Canonical text."}],
                }],
            },
        )
        piece.set_sponsor(user)
        piece.set_submitted_by(user)
        piece.save()
        working_copy = WorkingDocument.objects.create(
            piece=piece,
            user=user,
            auto_save_count=1,
            body_json={
                "type": "doc",
                "content": [
                    {"type": "heading", "content": [{"type": "text", "text": "Opening Notes"}]},
                    {"type": "paragraph", "content": []},
                    {"type": "paragraph", "content": [{"type": "text", "text": "First paragraph."}]},
                    {"type": "blockquote", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Second paragraph."}]},
                    ]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "Third paragraph."}]},
                ],
            },
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            "/api/writing/drafts",
            {"sponsor_type": "member", "sponsor_slug": user.username, "filter": "all"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["preview_paragraphs"],
            ["First paragraph.", "Second paragraph."],
        )
        self.assertNotIn("body_json", response.data[0])

        piece.body_json = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Imported opening."}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Imported follow-up."}]},
            ],
        }
        piece.save()
        working_copy.body_json = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Stale copy."}]}],
        }
        working_copy.auto_save_count = 0
        working_copy.save()

        imported_response = client.get(
            "/api/writing/drafts",
            {"sponsor_type": "member", "sponsor_slug": user.username, "filter": "all"},
        )
        self.assertEqual(imported_response.status_code, 200)
        self.assertEqual(
            imported_response.data[0]["preview_paragraphs"],
            ["Imported opening.", "Imported follow-up."],
        )
