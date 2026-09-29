# Phase 3 amendment to ADR-0054 (adr-0054-issue-amendment.md), P3-5:
# end-to-end test of the Issue rename + editorial fields, modeled on the
# real Issue #1 workflow: create, write description, order, mark lead,
# preview via Continuous Read, cascade-publish.

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from io import StringIO
from rest_framework import status
from rest_framework.test import APIClient

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from writing.models import Issue, IssuePlacement, WritingPiece

User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ],
    }


def _create_piece(*, author, title, slug, clean=True, sponsor=None):
    piece = WritingPiece(
        author=author,
        author_name=author.get_full_name() or author.username,
        title=title,
        excerpt=f"{title} excerpt",
        body_json=_body_json(f"{title} body"),
        status="draft",
        spellcheck_clean=clean,
        signed_off=clean,
    )
    piece.set_sponsor(sponsor or author)
    piece.slug = slug
    piece.set_submitted_by(author)
    piece.save()
    return piece


class IssueAmendmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="editor_user",
            email="editor@example.com",
            password="testpass123",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.pieces = [
            _create_piece(author=self.user, title=f"Article {i}", slug=f"article-{i}")
            for i in range(1, 6)
        ]

    def test_create_issue_with_editorial_fields(self):
        response = self.client.post("/api/writing/issues", {"title": "The Resourcefulness Issue"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        issue_id = response.data["id"]

        patch = self.client.patch(
            f"/api/writing/issues/{issue_id}",
            {"designation": "Issue #1", "description": _body_json("Welcome to Issue #1.")},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(patch.data["designation"], "Issue #1")
        self.assertEqual(patch.data["title"], "The Resourcefulness Issue")

        issue = Issue.objects.get(id=issue_id)
        self.assertEqual(issue.designation, "Issue #1")
        self.assertIsNotNone(issue.description)

    def test_list_issues_includes_placement_count_and_publishability(self):
        created = self.client.post(
            "/api/writing/issues", {"title": "The Resourcefulness Issue"}, format="json"
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        issue_id = created.data["id"]

        empty_list = self.client.get("/api/writing/issues")
        self.assertEqual(empty_list.status_code, status.HTTP_200_OK)
        self.assertEqual(empty_list.data[0]["member_count"], 0)
        self.assertFalse(empty_list.data[0]["is_publishable"])

        added = self.client.post(
            f"/api/writing/issues/{issue_id}/placements",
            {"piece_id": str(self.pieces[0].id)},
            format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)

        issue_list = self.client.get("/api/writing/issues")
        self.assertEqual(issue_list.status_code, status.HTTP_200_OK)
        self.assertEqual(issue_list.data[0]["member_count"], 1)
        self.assertTrue(issue_list.data[0]["is_publishable"])
        self.assertEqual(issue_list.data[0]["piece_ids"], [str(self.pieces[0].id)])

    def test_order_mark_lead_preview_and_publish(self):
        issue = Issue.objects.create(title="Issue #1", designation="Issue #1")
        from django.contrib.contenttypes.models import ContentType
        issue.sponsor_content_type = ContentType.objects.get_for_model(self.user)
        issue.sponsor_object_id = self.user.pk
        issue.description = _body_json("Welcome to the first Issue.")
        issue.save()

        # Add all five pieces as placements, in order.
        for piece in self.pieces:
            resp = self.client.post(
                f"/api/writing/issues/{issue.id}/placements",
                {"piece_id": str(piece.id)},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.assertEqual(IssuePlacement.objects.filter(issue=issue).count(), 5)

        # Mark the first piece as lead.
        lead_piece = self.pieces[0]
        resp = self.client.patch(
            f"/api/writing/issues/{issue.id}/placements/{lead_piece.id}",
            {"is_lead": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_lead"])

        # At most one lead per Issue — marking a second clears the first.
        second_piece = self.pieces[1]
        resp = self.client.patch(
            f"/api/writing/issues/{issue.id}/placements/{second_piece.id}",
            {"is_lead": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_lead"])
        first_placement = IssuePlacement.objects.get(issue=issue, piece=lead_piece)
        self.assertFalse(first_placement.is_lead)

        # Continuous Read preview — editor sees all placements including drafts.
        resp = self.client.get(f"/api/writing/issues/{issue.id}/read")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_editor"])
        self.assertEqual(len(resp.data["placements"]), 5)
        self.assertEqual(resp.data["description"], issue.description)
        # All pieces are still drafts pre-publish.
        self.assertTrue(all(p["status"] == "draft" for p in resp.data["placements"]))

        # A non-owner, non-superuser viewer sees only published pieces (none yet).
        other = User.objects.create_user(username="reader_user", email="reader@example.com", password="testpass123")
        other_client = APIClient()
        other_client.force_authenticate(user=other)
        resp = other_client.get(f"/api/writing/issues/{issue.id}/read")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["is_editor"])
        self.assertEqual(resp.data["placements"], [])

        # Cascade-publish — all pieces are spellcheck_clean + signed_off.
        resp = self.client.post(f"/api/writing/issues/{issue.id}/publish")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "published")
        for piece in self.pieces:
            piece.refresh_from_db()
            self.assertEqual(piece.status, "published")

        # Reader now sees all five, published, via Continuous Read.
        resp = other_client.get(f"/api/writing/issues/{issue.id}/read")
        self.assertEqual(len(resp.data["placements"]), 5)
        self.assertTrue(all(p["status"] == "published" for p in resp.data["placements"]))

        # Public reader route also reflects the published Issue.
        resp = self.client.get(f"/api/public/writing/issues/{issue.slug}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["designation"], "Issue #1")
        self.assertEqual(resp.data["piece_count"], 5)

    def test_group_issue_accepts_group_piece_and_isolated_from_member_issues(self):
        group = GroupService.create_group(
            title="Editorial Group", group_type="community", created_by=self.user,
            visibility="private",
        )
        ensure_user_membership(group, self.user, role="admin")
        group_piece = _create_piece(
            author=self.user, title="Group Article", slug="group-article", sponsor=group,
        )
        created = self.client.post(
            "/api/writing/issues",
            {"title": "Group Issue", "sponsor_type": "group", "sponsor_slug": group.slug},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        issue_id = created.data["id"]

        self.assertEqual(len(self.client.get("/api/writing/issues").data), 0)
        group_list = self.client.get(
            "/api/writing/issues", {"sponsor_type": "group", "sponsor_slug": group.slug}
        )
        self.assertEqual([item["id"] for item in group_list.data], [issue_id])

        added = self.client.post(
            f"/api/writing/issues/{issue_id}/placements",
            {"piece_id": str(group_piece.id)}, format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)
        self.assertEqual(IssuePlacement.objects.filter(issue_id=issue_id).count(), 1)
        refreshed_list = self.client.get(
            "/api/writing/issues", {"sponsor_type": "group", "sponsor_slug": group.slug}
        )
        self.assertEqual(refreshed_list.data[0]["piece_ids"], [str(group_piece.id)])
        cross_sponsor = self.client.post(
            f"/api/writing/issues/{issue_id}/placements",
            {"piece_id": str(self.pieces[0].id)}, format="json",
        )
        self.assertEqual(cross_sponsor.status_code, status.HTTP_403_FORBIDDEN)

        preview = self.client.get(f"/api/writing/issues/{issue_id}/read")
        self.assertTrue(preview.data["is_editor"])
        self.assertEqual(len(preview.data["placements"]), 1)

        outsider = User.objects.create_user(username="outsider", email="outsider@example.com")
        self.client.force_authenticate(user=outsider)
        self.assertEqual(
            self.client.get(
                "/api/writing/issues", {"sponsor_type": "group", "sponsor_slug": group.slug}
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"/api/writing/issues/{issue_id}/placements",
                {"piece_id": str(group_piece.id)}, format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        outsider_preview = self.client.get(f"/api/writing/issues/{issue_id}/read")
        self.assertEqual(outsider_preview.status_code, status.HTTP_404_NOT_FOUND)

    def test_reassign_issue_sponsor_requires_execute_and_matching_pieces(self):
        group = GroupService.create_group(
            title="Transfer Group", group_type="community", created_by=self.user,
            visibility="private",
        )
        created = self.client.post("/api/writing/issues", {"title": "Transfer Me"}, format="json")
        issue = Issue.objects.get(pk=created.data["id"])
        kwargs = {
            "issue_id": str(issue.pk),
            "from_member": self.user.username,
            "group_slug": group.slug,
        }
        call_command("reassign_issue_sponsor", stdout=StringIO(), **kwargs)
        issue.refresh_from_db()
        self.assertEqual(issue.sponsor_object_id, self.user.pk)

        IssuePlacement.objects.create(issue=issue, piece=self.pieces[0], order_index=0)
        with self.assertRaises(CommandError):
            call_command("reassign_issue_sponsor", execute=True, stdout=StringIO(), **kwargs)
        issue.placements.all().delete()

        group_piece = _create_piece(
            author=self.user, title="Group Transfer", slug="group-transfer", sponsor=group,
        )
        IssuePlacement.objects.create(issue=issue, piece=group_piece, order_index=0)
        call_command("reassign_issue_sponsor", execute=True, stdout=StringIO(), **kwargs)
        issue.refresh_from_db()
        self.assertEqual(issue.sponsor_object_id, group.pk)
        self.assertEqual(issue.placements.count(), 1)
