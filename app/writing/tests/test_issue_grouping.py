from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from publishing.models import ContentPlacement, PublicationGroup
from writing.models import Issue, IssuePlacement, WorkingDocument, WritingPiece


User = get_user_model()
BODY = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Content"}]}]}


class IssueGroupingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="writer", email="writer@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="testpass123")
        self.group = Group.objects.create(
            title="Editorial Group", slug="editorial-group", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
        )
        self.membership = GroupMembership.objects.create(
            group=self.group,
            member_content_type=ContentType.objects.get_for_model(User),
            member_object_id=self.user.pk,
            roles=["member"],
            is_active=True,
            is_pending=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def piece(self, sponsor, title, *, author=None, status="draft"):
        author = author or self.user
        piece = WritingPiece(
            author=author, title=title, body_json=BODY, status=status,
            published_at=timezone.now() if status == "published" else None,
        )
        piece.set_sponsor(sponsor)
        piece.set_submitted_by(author)
        piece.save()
        if status == "draft":
            WorkingDocument.objects.create(piece=piece, user=author, title=title, body_json=BODY)
        return piece

    def place_in_feed(self, piece):
        piece_ct = ContentType.objects.get_for_model(WritingPiece)
        publication = PublicationGroup.objects.create(
            created_by=self.user, source_content_type=piece_ct, source_object_id=piece.pk,
        )
        ContentPlacement.objects.create(
            publication_group=publication, placed_by=self.user,
            source_content_type=piece_ct, source_object_id=piece.pk,
            target_content_type=ContentType.objects.get_for_model(Group),
            target_object_id=self.group.pk, channel="feed", visibility="public", follow_updates=True,
        )

    def test_group_issue_preserves_placement_order_and_hides_inaccessible_drafts(self):
        self.membership.roles = ["member", "admin"]
        self.membership.save(update_fields=["roles"])
        first = self.piece(self.group, "First", status="published")
        second = self.piece(self.group, "Second", status="published")
        own_draft = self.piece(self.group, "My draft")
        hidden_draft = self.piece(self.group, "Other draft", author=self.other)
        self.place_in_feed(first)
        self.place_in_feed(second)
        issue = Issue.objects.create(
            title="Issue 1", sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=self.group.pk,
        )
        for piece, index in [(first, 2), (own_draft, 1), (second, 0), (hidden_draft, 3)]:
            IssuePlacement.objects.create(issue=issue, piece=piece, order_index=index)

        response = self.client.get("/api/writing/issues/grouping", {
            "sponsor_type": "group", "sponsor_slug": self.group.slug,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["piece_ids"], [str(second.pk), str(own_draft.pk), str(first.pk)])

    def test_member_view_includes_group_issue_only_while_membership_is_active(self):
        piece = self.piece(self.group, "Published", status="published")
        issue = Issue.objects.create(
            title="Group issue", sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=self.group.pk, status="published", published_at=timezone.now(),
        )
        IssuePlacement.objects.create(issue=issue, piece=piece, order_index=0)
        url = "/api/writing/issues/grouping"
        params = {"sponsor_type": "member", "sponsor_slug": self.user.username}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["piece_ids"], [str(piece.pk)])
        self.assertEqual(response.data[0]["sponsor_label"], self.group.title)

        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url, params).data, [])

    def test_draft_group_issue_is_hidden_from_regular_member_in_both_views(self):
        piece = self.piece(self.group, "Draft")
        issue = Issue.objects.create(
            title="Private editorial plan", sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=self.group.pk,
        )
        IssuePlacement.objects.create(issue=issue, piece=piece, order_index=0)
        self.assertEqual(self.client.get("/api/writing/issues/grouping", {
            "sponsor_type": "group", "sponsor_slug": self.group.slug,
        }).data, [])
        self.assertEqual(self.client.get("/api/writing/issues/grouping", {
            "sponsor_type": "member", "sponsor_slug": self.user.username,
        }).data, [])

    def test_member_issue_groups_personal_drafts_and_denies_other_members(self):
        piece = self.piece(self.user, "Personal draft")
        issue = Issue.objects.create(
            title="Personal issue", sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
        )
        IssuePlacement.objects.create(issue=issue, piece=piece, order_index=0)
        url = "/api/writing/issues/grouping"
        response = self.client.get(url, {"sponsor_type": "member", "sponsor_slug": self.user.username})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["piece_ids"], [str(piece.pk)])
        self.assertEqual(self.client.get(url, {
            "sponsor_type": "member", "sponsor_slug": self.other.username,
        }).status_code, 403)

    def test_nonmember_cannot_view_group_issue_grouping(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get("/api/writing/issues/grouping", {
            "sponsor_type": "group", "sponsor_slug": self.group.slug,
        })
        self.assertEqual(response.status_code, 403)
