from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from dispatch.models import DispatchCollaborator, DispatchContent
from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from writing.models import WorkingDocument, WritingPiece


def paragraph(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def document(*paragraphs):
    return {"type": "doc", "content": [paragraph(text) for text in paragraphs]}


class DraftSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="draft_searcher", email="searcher@example.com", password="pass"
        )
        self.other = get_user_model().objects.create_user(
            username="other_searcher", email="other-searcher@example.com", password="pass"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def make_draft(self, *, owner=None, sponsor=None, body=None, **fields):
        owner = owner or self.user
        piece = WritingPiece(
            author=owner, title="Opening notes", status="draft",
            body_json=document("Old canonical snapshot."),
        )
        piece.set_sponsor(sponsor or owner)
        piece.set_submitted_by(owner)
        piece.save()
        return WorkingDocument.objects.create(
            piece=piece, user=owner, body_json=body or document("Ordinary text."),
            auto_save_count=1, **fields,
        )

    def search(self, term=None, **params):
        query = {
            "sponsor_type": "member", "sponsor_slug": self.user.username, "filter": "all",
            **params,
        }
        if term is not None:
            query["search"] = term
        response = self.client.get("/api/writing/drafts", query)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_finds_body_only_phrase_beyond_all_previews(self):
        draft = self.make_draft(body=document(
            "An introduction. " * 100,
            "More opening thoughts.",
            "And to hold ourselves to design standards that favor asking only the merest "
            "amount of a person's time to accomplish tasks.",
        ))
        self.make_draft()
        rows = self.search(" DESIGN ")
        self.assertEqual([row["id"] for row in rows], [str(draft.pk)])
        self.assertNotIn("design", rows[0]["body_preview"].lower())
        self.assertNotIn("design", " ".join(rows[0]["preview_paragraphs"]).lower())
        self.assertNotIn("body_json", rows[0])
        self.assertEqual(len(self.search("merest amount of a person's time")), 1)
        self.assertEqual(self.search("nonexistent"), [])

    def test_searches_title_excerpt_and_words_split_by_marks(self):
        title = self.make_draft(title="Design notes")
        excerpt = self.make_draft(excerpt="Design summary")
        inline = self.make_draft(body={"type": "doc", "content": [{
            "type": "paragraph", "content": [
                {"type": "text", "text": "de"},
                {"type": "text", "text": "sign", "marks": [{"type": "bold"}]},
            ],
        }]})
        self.assertEqual(
            {row["id"] for row in self.search("design")}, {str(title.pk), str(excerpt.pk), str(inline.pk)}
        )

    def test_empty_search_preserves_browse_and_latest_save_replaces_matches(self):
        draft = self.make_draft(body=document("Design thinking."))
        self.assertEqual(self.search(), self.search("   "))
        self.assertEqual(len(self.search("design")), 1)
        draft.body_json = document("Revised to discuss gardening.")
        draft.save()
        self.assertEqual(self.search("design"), [])
        self.assertEqual(len(self.search("gardening")), 1)
        # A stale published snapshot must not reintroduce removed draft text.
        draft.piece.body_json = document("Design thinking.")
        draft.piece.save()
        self.assertEqual(self.search("design"), [])

    def test_never_saved_import_uses_same_body_as_list_preview(self):
        draft = self.make_draft(body=document(""))
        draft.auto_save_count = 0
        draft.save()
        draft.piece.body_json = document("Imported introduction.", "Imported design standards.")
        draft.piece.save()
        self.assertEqual([row["id"] for row in self.search("design")], [str(draft.pk)])

    def test_search_does_not_expand_owner_sponsor_or_status_scope(self):
        own = self.make_draft(body=document("Design standards."))
        self.make_draft(owner=self.other, body=document("Design private notes."))
        self.make_draft(sponsor=self.other, body=document("Design another sponsor."))
        published = self.make_draft(body=document("Design published text."))
        published.piece.status = "published"
        published.piece.published_at = timezone.now()
        published.piece.save()
        self.assertEqual([row["id"] for row in self.search("design")], [str(own.pk)])
        self.assertEqual(self.search("private", sponsor_slug=self.other.username), [])
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/writing/drafts", {
            "sponsor_type": "member", "sponsor_slug": self.user.username, "search": "design",
        })
        self.assertIn(response.status_code, (401, 403))

    def test_shared_group_search_requires_assignment_and_current_membership(self):
        group = GroupService.create_group(
            title="Search Group", group_type="community", created_by=self.other,
            visibility="private",
        )
        membership = ensure_user_membership(group, self.user, role="member")
        shared = self.make_draft(owner=self.other, sponsor=group, body=document("Design collaboration."))
        dispatch = DispatchContent.objects.create(created_by=self.other)
        shared.dispatch_content = dispatch
        shared.save()
        DispatchCollaborator.objects.create(content=dispatch, user=self.user, role="editor")
        self.make_draft(owner=self.other, sponsor=group, body=document("Design private solo draft."))
        params = {"sponsor_type": "group", "sponsor_slug": group.slug}
        self.assertEqual([row["id"] for row in self.search("design", **params)], [str(shared.pk)])
        self.assertEqual(self.search("design", filter="my", **params), [])
        self.assertEqual(len(self.search("design", filter="shared", **params)), 1)
        # Stale collaboration assignments cannot bypass the list's live group gate.
        membership.is_active = False
        membership.save()
        self.assertEqual(self.search("design", **params), [])
