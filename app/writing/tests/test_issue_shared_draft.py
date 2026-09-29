from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from writing.models import Issue, WorkingDocument, WritingPiece


User = get_user_model()


def body(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


class IssueSharedDraftTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="issue_author", email="author@example.com", password="pass")
        self.steward = User.objects.create_user(username="issue_steward", email="steward@example.com", password="pass")
        self.group = GroupService.create_group(
            title="Shared Draft Group", group_type="community", created_by=self.author,
            visibility="private",
        )
        ensure_user_membership(self.group, self.author, role="admin")
        ensure_user_membership(self.group, self.steward, role="steward")
        self.piece = WritingPiece(author=self.author, title="Shared article", body_json=body("Original"), status="draft")
        self.piece.set_sponsor(self.group)
        self.piece.set_submitted_by(self.author)
        self.piece.save()
        self.draft = WorkingDocument.objects.create(
            piece=self.piece, user=self.author, title=self.piece.title, body_json=body("Original"),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.steward)

    def test_steward_and_author_edit_one_revisioned_draft(self):
        url = f"/api/writing/pieces/{self.piece.pk}/working-copy"
        loaded = self.client.get(url)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(str(loaded.data["id"]), str(self.draft.pk))

        saved = self.client.put(url, {
            "body_json": body("Steward edit"), "expected_auto_save_count": 0,
        }, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.data["auto_save_count"], 1)
        self.assertEqual(WorkingDocument.objects.filter(piece=self.piece).count(), 1)

        stale = self.client.put(url, {
            "body_json": body("Stale edit"), "expected_auto_save_count": 0,
        }, format="json")
        self.assertEqual(stale.status_code, 409)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.body_json, body("Steward edit"))

        self.client.force_authenticate(user=self.author)
        self.assertEqual(self.client.get(url).data["body_json"], body("Steward edit"))

    def test_review_signoff_and_publish_exact_draft(self):
        self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "body_json": body("Reviewed version"), "expected_auto_save_count": 0,
        }, format="json")
        review = self.client.post(f"/api/writing/pieces/{self.piece.pk}/spelling-review", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(review.status_code, 200)
        signoff = self.client.post(f"/api/writing/pieces/{self.piece.pk}/sign-off", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(signoff.status_code, 200)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.body_json, body("Reviewed version"))
        self.assertEqual(self.piece.signed_off_by_id, self.steward.pk)

        self.client.force_authenticate(user=self.author)
        created = self.client.post("/api/writing/issues", {
            "title": "Reviewed Issue", "sponsor_type": "group", "sponsor_slug": self.group.slug,
        }, format="json")
        self.assertEqual(created.status_code, 201)
        issue = Issue.objects.get(pk=created.data["id"])
        added = self.client.post(f"/api/writing/issues/{issue.pk}/placements", {
            "piece_id": str(self.piece.pk),
        }, format="json")
        self.assertEqual(added.status_code, 201)
        published = self.client.post(f"/api/writing/issues/{issue.pk}/publish")
        self.assertEqual(published.status_code, 200)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.body_json, body("Reviewed version"))
        self.assertEqual(self.piece.status, "published")

    def test_edit_after_approval_clears_both_gates(self):
        self.client.post(f"/api/writing/pieces/{self.piece.pk}/spelling-review", {
            "expected_auto_save_count": 0,
        }, format="json")
        self.client.post(f"/api/writing/pieces/{self.piece.pk}/sign-off", {
            "expected_auto_save_count": 0,
        }, format="json")
        self.piece.refresh_from_db()
        self.assertTrue(self.piece.spellcheck_clean and self.piece.signed_off)

        edited = self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "body_json": body("Changed after approval"), "expected_auto_save_count": 0,
        }, format="json")
        self.assertEqual(edited.status_code, 200)
        self.piece.refresh_from_db()
        self.assertFalse(self.piece.spellcheck_clean)
        self.assertFalse(self.piece.signed_off)
        self.assertIsNone(self.piece.signed_off_by)
        self.assertEqual(self.piece.body_json, body("Original"))
