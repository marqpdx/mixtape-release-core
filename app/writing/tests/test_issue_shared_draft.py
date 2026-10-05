from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from io import StringIO

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from writing.models import Issue, WorkingDocument, WritingPiece, body_json_has_content


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

    def test_draft_title_and_body_remain_visible_when_piece_is_empty(self):
        self.piece.title = ""
        self.piece.body_json = {"type": "doc", "content": []}
        self.piece.save(update_fields=["title", "body_json", "is_empty"])
        self.draft.title = "Resourcefulness"
        self.draft.body_json = body("Saved draft content")
        self.draft.auto_save_count = 1
        self.draft.save()

        self.client.force_authenticate(user=self.author)
        created = self.client.post("/api/writing/issues", {
            "title": "Issue 1", "sponsor_type": "group", "sponsor_slug": self.group.slug,
        }, format="json")
        issue = Issue.objects.get(pk=created.data["id"])
        self.client.post(f"/api/writing/issues/{issue.pk}/placements", {
            "piece_id": str(self.piece.pk),
        }, format="json")

        listed = self.client.get("/api/writing/drafts", {
            "sponsor_type": "group", "sponsor_slug": self.group.slug,
        })
        self.assertEqual(listed.status_code, 200)
        self.assertIn(str(self.draft.pk), [str(item["id"]) for item in listed.data])
        restored = next(item for item in listed.data if str(item["id"]) == str(self.draft.pk))
        self.assertTrue(restored["draft_content_mismatch"])

        detail = self.client.get(f"/api/writing/issues/{issue.pk}")
        self.assertEqual(detail.data["placements"][0]["piece_title"], "Resourcefulness")
        read = self.client.get(f"/api/writing/issues/{issue.pk}/read")
        self.assertEqual(read.data["placements"][0]["title"], "Resourcefulness")
        self.assertEqual(read.data["placements"][0]["body_json"], body("Saved draft content"))

        reconciled = self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "title": "Resourcefulness Revised", "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(reconciled.status_code, 200)
        self.piece.refresh_from_db()
        self.assertFalse(self.piece.is_empty)
        self.assertEqual(self.piece.title, "Resourcefulness Revised")
        self.assertEqual(self.piece.body_json, {"type": "doc", "content": []})
        self.piece.save()
        self.piece.refresh_from_db()
        self.assertFalse(self.piece.is_empty)

    def test_title_edit_requires_new_review_and_promotes_with_body(self):
        edited = self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "title": "Resourcefulness", "body_json": body("Reviewed version"),
            "expected_auto_save_count": 0,
        }, format="json")
        self.assertEqual(edited.status_code, 200)
        review = self.client.post(f"/api/writing/pieces/{self.piece.pk}/spelling-review", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(review.status_code, 200)
        signoff = self.client.post(f"/api/writing/pieces/{self.piece.pk}/sign-off", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(signoff.status_code, 200)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.title, "Resourcefulness")
        self.assertEqual(self.piece.body_json, body("Reviewed version"))

        changed = self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "title": "Resourcefulness Revised", "expected_auto_save_count": 1,
        }, format="json")
        self.assertEqual(changed.status_code, 200)
        self.piece.refresh_from_db()
        self.assertFalse(self.piece.spellcheck_clean)
        self.assertFalse(self.piece.signed_off)

    def test_reconcile_command_only_repairs_empty_flag_when_executed(self):
        self.piece.body_json = {"type": "doc", "content": []}
        self.piece.save(update_fields=["body_json", "is_empty"])
        self.draft.title = "Resourcefulness"
        self.draft.body_json = body("Saved draft content")
        self.draft.auto_save_count = 1
        self.draft.save()
        issue = Issue.objects.create(title="Issue 1")
        from writing.models import IssuePlacement
        IssuePlacement.objects.create(issue=issue, piece=self.piece)

        output = StringIO()
        call_command("reconcile_issue_draft", working_document_id=str(self.draft.pk), stdout=output)
        self.piece.refresh_from_db()
        self.assertTrue(self.piece.is_empty)
        self.assertIn("Dry run only", output.getvalue())

        call_command("reconcile_issue_draft", working_document_id=str(self.draft.pk), execute=True, stdout=StringIO())
        self.piece.refresh_from_db()
        self.assertFalse(self.piece.is_empty)
        self.assertEqual(self.piece.title, "Resourcefulness")
        self.assertEqual(self.piece.body_json, {"type": "doc", "content": []})

    def test_issue_publish_rejects_title_changed_after_signoff(self):
        self.client.put(f"/api/writing/pieces/{self.piece.pk}/working-copy", {
            "title": "Resourcefulness", "body_json": body("Reviewed version"),
            "expected_auto_save_count": 0,
        }, format="json")
        self.client.post(f"/api/writing/pieces/{self.piece.pk}/spelling-review", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.client.post(f"/api/writing/pieces/{self.piece.pk}/sign-off", {
            "expected_auto_save_count": 1,
        }, format="json")
        self.client.force_authenticate(user=self.author)
        created = self.client.post("/api/writing/issues", {
            "title": "Issue 1", "sponsor_type": "group", "sponsor_slug": self.group.slug,
        }, format="json")
        issue = Issue.objects.get(pk=created.data["id"])
        self.client.post(f"/api/writing/issues/{issue.pk}/placements", {
            "piece_id": str(self.piece.pk),
        }, format="json")

        WorkingDocument.objects.filter(pk=self.draft.pk).update(title="Unapproved title")
        rejected = self.client.post(f"/api/writing/issues/{issue.pk}/publish")
        self.assertEqual(rejected.status_code, 400)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.status, "draft")

        WorkingDocument.objects.filter(pk=self.draft.pk).update(title="Resourcefulness")
        published = self.client.post(f"/api/writing/issues/{issue.pk}/publish")
        self.assertEqual(published.status_code, 200)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.title, "Resourcefulness")
        self.assertEqual(self.piece.status, "published")
        self.assertEqual(self.piece.versions.count(), 1)
        version = self.piece.versions.first()
        self.assertEqual(version.title, "Resourcefulness")
        self.assertEqual(version.body_json, body("Reviewed version"))
        self.assertEqual(self.piece.current_version_no, version.sequence_no)
        WorkingDocument.objects.filter(pk=self.draft.pk).update(
            title="Later draft title", body_json=body("Later draft body"),
        )
        read = self.client.get(f"/api/writing/issues/{issue.pk}/read")
        self.assertEqual(read.data["placements"][0]["title"], "Resourcefulness")
        self.assertEqual(read.data["placements"][0]["body_json"], body("Reviewed version"))

    def test_nested_draft_content_is_not_empty(self):
        nested = {
            "type": "doc",
            "content": [{"type": "bulletList", "content": [
                {"type": "listItem", "content": [body("Nested text")["content"][0]]},
            ]}],
        }
        self.assertTrue(body_json_has_content(nested))

    def test_draft_lists_hide_empty_placeholders_but_keep_titled_drafts(self):
        titled_piece = WritingPiece(author=self.author, title="", body_json={}, status="draft")
        titled_piece.set_sponsor(self.group)
        titled_piece.set_submitted_by(self.author)
        titled_piece.save()
        titled = WorkingDocument.objects.create(
            piece=titled_piece, user=self.author, title="Outline to write", body_json={},
        )
        empty_piece = WritingPiece(author=self.author, title="", body_json={}, status="draft")
        empty_piece.set_sponsor(self.group)
        empty_piece.set_submitted_by(self.author)
        empty_piece.save()
        empty = WorkingDocument.objects.create(
            piece=empty_piece, user=self.author, title="",
            body_json={"type": "doc", "content": [{"type": "paragraph"}]},
        )

        self.client.force_authenticate(user=self.author)
        listed = self.client.get("/api/writing/drafts", {
            "sponsor_type": "group", "sponsor_slug": self.group.slug,
        })
        ids = {str(item["id"]) for item in listed.data}
        self.assertIn(str(titled.pk), ids)
        self.assertNotIn(str(empty.pk), ids)

        self.author.is_superuser = True
        self.author.save(update_fields=["is_superuser"])
        recent = self.client.get("/api/writing/drafts/recent", {"limit": 1})
        self.assertEqual(recent.status_code, 200)
        self.assertEqual([str(item["id"]) for item in recent.data], [str(titled.pk)])
