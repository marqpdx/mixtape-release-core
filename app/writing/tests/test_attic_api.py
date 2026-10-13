import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from writing.models import AtticEntry, WorkingDocument, WritingPiece

User = get_user_model()


def document(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


class AtticApiTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="attic_author", password="pass")
        self.other = User.objects.create_user(username="attic_other", password="pass")
        self.piece = self.create_piece("Manuscript", document("Original"))
        self.draft = WorkingDocument.objects.create(piece=self.piece, user=self.author, body_json=document("Working draft"))
        self.url = f"/api/writing/pieces/{self.piece.pk}/attic"
        self.client = APIClient()
        self.client.force_authenticate(self.author)
        self.payload = {
            "id": str(uuid.uuid4()),
            "slice_json": {"content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Keep this", "marks": [{"type": "bold"}]},
            ]}], "openStart": 1, "openEnd": 1},
            "text": "Keep this", "source_title": "Manuscript", "source_context": "Before […] after",
        }

    def results(self, response):
        return response.data["results"] if isinstance(response.data, dict) else response.data

    def create_piece(self, title, body=None):
        piece = WritingPiece(author=self.author, title=title, body_json=body or {})
        piece.set_sponsor(self.author)
        piece.set_submitted_by(self.author)
        piece.save()
        return piece

    def test_capture_preserves_formatting_and_never_changes_manuscript(self):
        response = self.client.post(self.url, self.payload, format="json")
        self.assertEqual(response.status_code, 201)
        entry = AtticEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.piece, self.piece)
        self.assertEqual(entry.created_by, self.author)
        self.assertEqual(entry.slice_json, self.payload["slice_json"])
        self.draft.refresh_from_db()
        self.piece.refresh_from_db()
        self.assertEqual(self.draft.body_json, document("Working draft"))
        self.assertEqual(self.draft.auto_save_count, 0)
        self.assertEqual(self.piece.body_json, document("Original"))
        self.assertEqual(self.results(self.client.get(self.url))[0]["source_context"], "Before […] after")

    def test_retry_is_idempotent_and_changed_capture_cannot_overwrite(self):
        self.assertEqual(self.client.post(self.url, self.payload, format="json").status_code, 201)
        self.assertEqual(self.client.post(self.url, self.payload, format="json").status_code, 200)
        self.assertEqual(AtticEntry.objects.count(), 1)
        changed = {**self.payload, "text": "Changed"}
        self.assertEqual(self.client.post(self.url, changed, format="json").status_code, 409)
        self.assertEqual(AtticEntry.objects.get().text, "Keep this")

    def test_authentication_and_piece_edit_permission_required(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload, format="json").status_code, 403)
        self.assertFalse(AtticEntry.objects.exists())

    def test_lists_are_piece_scoped_and_hide_deleted_entries(self):
        self.client.post(self.url, self.payload, format="json")
        other_piece = self.create_piece("Other manuscript")
        other_url = f"/api/writing/pieces/{other_piece.pk}/attic"
        self.assertEqual(self.results(self.client.get(other_url)), [])
        self.assertEqual(self.client.post(other_url, self.payload, format="json").status_code, 409)
        from django.utils import timezone
        AtticEntry.objects.update(deleted_at=timezone.now())
        self.assertEqual(self.results(self.client.get(self.url)), [])

    def test_group_editor_can_access_attic_but_regular_member_cannot(self):
        group = GroupService.create_group(title="Attic group", group_type="community", created_by=self.author, visibility="private")
        ensure_user_membership(group, self.author, role="admin")
        ensure_user_membership(group, self.other, role="steward")
        self.piece.set_sponsor(group)
        self.piece.save()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(self.url, self.payload, format="json").status_code, 201)
        self.client.force_authenticate(self.author)
        self.assertEqual(len(self.results(self.client.get(self.url))), 1)
        reader = User.objects.create_user(username="attic_reader", password="pass")
        ensure_user_membership(group, reader, role="member")
        self.client.force_authenticate(reader)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_invalid_selections_are_rejected_without_creating_entries(self):
        for selection in ({}, {"content": []}, {"content": ["bad"]},
                          {"content": [{"type": "text", "text": 123}]},
                          {"content": [{"type": "paragraph"}], "openStart": -1}):
            with self.subTest(selection=selection):
                response = self.client.post(self.url, {**self.payload, "slice_json": selection}, format="json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(AtticEntry.objects.exists())
