# Phase 3 amendment to ADR-0054 (adr-0054-issue-amendment.md), P3-5:
# end-to-end test of the Issue rename + editorial fields, modeled on the
# real Issue #1 workflow: create, write description, order, mark lead,
# preview via Continuous Read, cascade-publish.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from io import StringIO
from rest_framework import status
from rest_framework.test import APIClient

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
from publishing.models import ContentPlacement
from writing.publish_service import ensure_published_feed_placement
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

    def test_add_placement_at_position_and_append_after_first(self):
        created = self.client.post("/api/writing/issues", {"title": "Ordered Issue"}, format="json")
        issue_id = created.data["id"]
        url = f"/api/writing/issues/{issue_id}/placements"

        for piece in (self.pieces[0], self.pieces[2]):
            response = self.client.post(url, {"piece_id": str(piece.id)}, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            list(IssuePlacement.objects.filter(issue_id=issue_id).order_by("order_index").values_list("order_index", flat=True)),
            [0, 1],
        )

        inserted = self.client.post(
            url,
            {"piece_id": str(self.pieces[1].id), "before_piece_id": str(self.pieces[2].id)},
            format="json",
        )
        self.assertEqual(inserted.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            list(IssuePlacement.objects.filter(issue_id=issue_id).order_by("order_index").values_list("piece_id", flat=True)),
            [piece.id for piece in self.pieces[:3]],
        )

        invalid = self.client.post(
            url,
            {"piece_id": str(self.pieces[3].id), "before_piece_id": str(self.pieces[4].id)},
            format="json",
        )
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(IssuePlacement.objects.filter(issue_id=issue_id, piece=self.pieces[3]).exists())

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

    def test_group_issue_publish_places_all_pieces_and_retracts_to_drafts(self):
        group = GroupService.create_group(
            title="Public Editorial Group", group_type="community", created_by=self.user,
            visibility="public",
        )
        ensure_user_membership(group, self.user, role="admin")
        pieces = [
            _create_piece(author=self.user, title=f"Group Article {i}", slug=f"group-article-{i}", sponsor=group)
            for i in range(3)
        ]
        created = self.client.post("/api/writing/issues", {
            "title": "Public Group Issue", "sponsor_type": "group", "sponsor_slug": group.slug,
        }, format="json")
        issue = Issue.objects.get(pk=created.data["id"])
        for piece in pieces:
            self.assertEqual(self.client.post(f"/api/writing/issues/{issue.pk}/placements", {
                "piece_id": str(piece.pk),
            }, format="json").status_code, 201)

        pieces[0].publish()
        existing = ensure_published_feed_placement(pieces[0], self.user, group)
        pieces[1].publish()
        original_versions = [pieces[0].versions.count(), pieces[1].versions.count()]

        published = self.client.post(f"/api/writing/issues/{issue.pk}/publish")
        self.assertEqual(published.status_code, 200, published.data)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)
        group_ct = ContentType.objects.get_for_model(group)
        for piece in pieces:
            piece.refresh_from_db()
            self.assertEqual(piece.status, "published")
            placement = ContentPlacement.objects.get(
                source_content_type=piece_ct, source_object_id=piece.pk,
                target_content_type=group_ct, target_object_id=group.pk, channel="feed",
            )
            self.assertEqual(placement.visibility, "public")
            self.assertEqual(placement.locked_artifact_object_id, piece.versions.latest("sequence_no").pk)
            if piece.pk == pieces[0].pk:
                self.assertEqual(placement.pk, existing.pk)
        self.assertEqual([pieces[0].versions.count(), pieces[1].versions.count()], original_versions)

        feed = self.client.get("/api/writing/placements", {
            "sponsor_type": "group", "sponsor_slug": group.slug,
        })
        self.assertEqual(len(feed.data), 3)
        reader = APIClient()
        for piece in pieces:
            self.assertEqual(reader.get(f"/api/groups/{group.slug}/writing/{piece.slug}").status_code, 200)

        issue_only = self.client.post(f"/api/writing/issues/{issue.pk}/unpublish", {
            "cascade": False,
        }, format="json")
        self.assertEqual(issue_only.status_code, 200)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "draft")
        self.assertTrue(all(WritingPiece.objects.get(pk=p.pk).status == "published" for p in pieces))

        cascade = self.client.post(f"/api/writing/issues/{issue.pk}/unpublish", {
            "cascade": True,
        }, format="json")
        self.assertEqual(cascade.status_code, 200)
        self.assertTrue(all(WritingPiece.objects.get(pk=p.pk).status == "draft" for p in pieces))
        self.assertEqual(len(self.client.get("/api/writing/placements", {
            "sponsor_type": "group", "sponsor_slug": group.slug,
        }).data), 0)
        for piece in pieces:
            self.assertEqual(reader.get(f"/api/groups/{group.slug}/writing/{piece.slug}").status_code, 404)

    def test_cascade_refuses_piece_in_another_published_issue(self):
        piece = self.pieces[0]
        issue = Issue.objects.create(
            title="First Issue", sponsor_content_type=ContentType.objects.get_for_model(self.user),
            sponsor_object_id=self.user.pk, status="published",
        )
        other = Issue.objects.create(
            title="Other Issue", sponsor_content_type=issue.sponsor_content_type,
            sponsor_object_id=self.user.pk, status="published",
        )
        IssuePlacement.objects.create(issue=issue, piece=piece)
        IssuePlacement.objects.create(issue=other, piece=piece)
        piece.status = "published"
        piece.published_at = issue.created_at
        piece.save(update_fields=["status", "published_at"])

        response = self.client.post(f"/api/writing/issues/{issue.pk}/unpublish", {
            "cascade": True,
        }, format="json")
        self.assertEqual(response.status_code, 409)
        issue.refresh_from_db()
        piece.refresh_from_db()
        self.assertEqual(issue.status, "published")
        self.assertEqual(piece.status, "published")

    def test_group_publisher_can_prepare_distribution_for_another_authors_piece(self):
        author = User.objects.create_user(username="guest_writer", password="testpass123")
        outsider = User.objects.create_user(username="outsider_writer", password="testpass123")
        group = GroupService.create_group(
            title="Publisher Group", group_type="community", created_by=self.user,
            visibility="public",
        )
        ensure_user_membership(group, self.user, role="admin")
        piece = _create_piece(author=author, title="Guest Article", slug="guest-article", sponsor=group)
        piece.publish()
        url = f"/api/distribution/pieces/{piece.pk}/distribute"

        # Invalid payload reaches validation for the group publisher, but not for an outsider.
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        other_client = APIClient()
        other_client.force_authenticate(user=outsider)
        self.assertEqual(other_client.post(url, {}, format="json").status_code, 403)

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
