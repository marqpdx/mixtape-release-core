from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from groups.models import Group, GroupMembership
from lanternmail.models import LanternmailList, LanternmailPost
from publishing.models import ContentPlacement, PublicationGroup
from writing.models import WritingPiece, WritingVersion


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


class FakeListmonkClient:
    def __init__(self):
        self.created_campaigns = []
        self.updated_campaigns = []
        self.status_updates = []
        self.test_sends = []

    def create_campaign(self, **kwargs):
        self.created_campaigns.append(kwargs)
        return {"data": {"id": 12345}}

    def update_campaign(self, **kwargs):
        self.updated_campaigns.append(kwargs)
        return {"data": {"id": kwargs["campaign_id"]}}

    def update_campaign_status(self, campaign_id: int, status: str):
        self.status_updates.append({"campaign_id": campaign_id, "status": status})
        return {"data": {"id": campaign_id, "status": status}}

    def get_campaign(self, campaign_id: int):
        return {"data": {"id": campaign_id, "body": "Body", "lists": []}}

    def test_campaign(self, campaign_id: int, subscribers: list[str]):
        self.test_sends.append({"campaign_id": campaign_id, "subscribers": subscribers})
        return {"data": {"id": campaign_id, "subscribers": subscribers}}


def _create_group(*, sponsor_user: User, title: str, slug: str) -> Group:
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type="community",
        decorators=[],
        additional_permissions=[],
    )
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username
    group.save()
    return group


def _create_membership(*, group: Group, user: User, roles: list[str]) -> GroupMembership:
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.create(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        roles=roles,
        is_active=True,
        is_pending=False,
    )


class LanternmailPostApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="lantern_admin",
            email="lantern_admin@test.com",
            password="testpass123",
        )
        self.member = User.objects.create_user(
            username="lantern_member",
            email="lantern_member@test.com",
            password="testpass123",
        )
        self.manager = User.objects.create_user(
            username="lantern_manager",
            email="lantern_manager@test.com",
            password="testpass123",
        )
        self.outsider = User.objects.create_user(
            username="lantern_outsider",
            email="lantern_outsider@test.com",
            password="testpass123",
        )
        self.group = _create_group(
            sponsor_user=self.admin,
            title="Lantern Group",
            slug="lantern-group",
        )
        _create_membership(group=self.group, user=self.admin, roles=["admin"])
        _create_membership(group=self.group, user=self.member, roles=["member"])
        manager_membership = _create_membership(
            group=self.group,
            user=self.manager,
            roles=["member"],
        )
        manager_membership.add_decorator("can__ManageLanternmail", assigned_by=self.admin)

        self.mailing_list = LanternmailList.objects.create(
            group=self.group,
            listmonk_id=9901,
            listmonk_uuid="00000000-0000-0000-0000-000000009901",
            display_name="Main List",
            listmonk_name="lantern-group--main-list",
            description="Primary list",
        )
        self.posts_url = f"/api/groups/{self.group.slug}/lanternmail/posts"

    def _create_lantern_placement(
        self,
        *,
        channel: str = "lantern",
        title: str = "Placed Writing",
        body_text: str = "Placed body",
        overrides: dict | None = None,
    ) -> ContentPlacement:
        piece = WritingPiece(
            author=self.admin,
            author_name=self.admin.username,
            title=title,
            excerpt="Placed excerpt",
            body_json=_body_json("current draft body"),
            status="published",
            published_at=timezone.now(),
        )
        piece.set_sponsor(self.group)
        piece.set_submitted_by(self.admin)
        piece.save()

        version = WritingVersion.objects.create(
            writing_piece=piece,
            sequence_no=1,
            version_label="1",
            body_json=_body_json(body_text),
            title=title,
            excerpt="Placed excerpt",
            kind="release",
            created_by=self.admin,
        )
        piece.current_version_no = 1
        piece.save(update_fields=["current_version_no", "updated_at"])

        piece_ct = ContentType.objects.get_for_model(WritingPiece)
        group_ct = ContentType.objects.get_for_model(Group)
        version_ct = ContentType.objects.get_for_model(WritingVersion)
        publication_group = PublicationGroup.objects.create(
            created_by=self.admin,
            source_content_type=piece_ct,
            source_object_id=piece.id,
        )
        return ContentPlacement.objects.create(
            publication_group=publication_group,
            placed_by=self.admin,
            source_content_type=piece_ct,
            source_object_id=piece.id,
            target_content_type=group_ct,
            target_object_id=self.group.id,
            channel=channel,
            visibility="members",
            follow_updates=False,
            locked_artifact_content_type=version_ct,
            locked_artifact_object_id=version.id,
            overrides=overrides or {},
        )

    def _create_published_piece(
        self,
        *,
        group: Group | None = None,
        title: str = "Published Writing",
        body_text: str = "Published body",
    ) -> WritingPiece:
        target_group = group or self.group
        piece = WritingPiece(
            author=self.admin,
            author_name=self.admin.username,
            title=title,
            excerpt="Published excerpt",
            body_json=_body_json("current draft body"),
            status="published",
            published_at=timezone.now(),
        )
        piece.set_sponsor(target_group)
        piece.set_submitted_by(self.admin)
        piece.save()

        WritingVersion.objects.create(
            writing_piece=piece,
            sequence_no=1,
            version_label="1",
            body_json=_body_json(body_text),
            title=title,
            excerpt="Published excerpt",
            kind="release",
            created_by=self.admin,
        )
        piece.current_version_no = 1
        piece.save(update_fields=["current_version_no", "updated_at"])
        return piece

    def test_admin_can_create_and_list_posts(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.posts_url,
            data={
                "title": "September Note",
                "subject": "A September note",
                "audience_kind": "subscribers",
                "mailing_list": self.mailing_list.id,
                "metadata": {"origin": "test"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "September Note")
        self.assertEqual(response.data["status"], LanternmailPost.STATUS_DRAFT)
        self.assertIsNone(response.data["listmonk_campaign_id"])
        self.assertIsNone(response.data["sent_at"])
        self.assertEqual(response.data["ingest_status"], LanternmailPost.INGEST_PENDING)

        list_response = self.client.get(self.posts_url)

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["created_by_display"], self.admin.username)

    def test_member_without_lanternmail_permission_gets_403(self):
        self.client.force_authenticate(user=self.member)

        response = self.client.get(self.posts_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_with_lanternmail_decorator_can_create_post(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.posts_url,
            data={"title": "Manager Note", "subject": "Manager subject"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created_by_display"], self.manager.username)

    def test_invalid_status_transition_is_rejected(self):
        self.client.force_authenticate(user=self.admin)
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Draft subject",
        )

        response = self.client.patch(
            f"{self.posts_url}/{post.id}",
            data={"status": LanternmailPost.STATUS_READY},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        post.refresh_from_db()
        self.assertEqual(post.status, LanternmailPost.STATUS_DRAFT)

    def test_patch_blocks_sent_transition(self):
        self.client.force_authenticate(user=self.admin)
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Ready",
            subject="Ready subject",
            status=LanternmailPost.STATUS_READY,
        )

        response = self.client.patch(
            f"{self.posts_url}/{post.id}",
            data={"status": LanternmailPost.STATUS_SENT},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("/send endpoint", response.data["error"])

    def test_only_draft_or_review_posts_can_be_deleted(self):
        self.client.force_authenticate(user=self.admin)
        ready_post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Ready",
            subject="Ready subject",
            status=LanternmailPost.STATUS_READY,
        )
        draft_post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Draft subject",
        )

        blocked = self.client.delete(f"{self.posts_url}/{ready_post.id}")
        allowed = self.client.delete(f"{self.posts_url}/{draft_post.id}")

        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(allowed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(LanternmailPost.objects.filter(id=ready_post.id).exists())

    def test_sync_campaign_creates_and_stores_listmonk_campaign_id(self):
        self.client.force_authenticate(user=self.admin)
        fake_client = FakeListmonkClient()
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Draft subject",
            body_text="Draft body",
            mailing_list=self.mailing_list,
        )

        with patch("lanternmail.api.views.get_listmonk_client", return_value=fake_client):
            response = self.client.post(f"{self.posts_url}/{post.id}/sync-campaign")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post.refresh_from_db()
        self.assertEqual(post.listmonk_campaign_id, 12345)
        self.assertEqual(len(fake_client.created_campaigns), 1)
        self.assertEqual(fake_client.created_campaigns[0]["subject"], "Draft subject")
        self.assertEqual(fake_client.created_campaigns[0]["list_ids"], [self.mailing_list.listmonk_id])

    def test_sync_campaign_updates_existing_listmonk_campaign(self):
        self.client.force_authenticate(user=self.admin)
        fake_client = FakeListmonkClient()
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Updated subject",
            body_text="Updated body",
            mailing_list=self.mailing_list,
            listmonk_campaign_id=222,
        )

        with patch("lanternmail.api.views.get_listmonk_client", return_value=fake_client):
            response = self.client.post(f"{self.posts_url}/{post.id}/sync-campaign")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(fake_client.updated_campaigns), 1)
        self.assertEqual(fake_client.updated_campaigns[0]["campaign_id"], 222)
        self.assertEqual(fake_client.updated_campaigns[0]["body"], "Updated body")

    def test_test_post_syncs_campaign_then_sends_test(self):
        self.client.force_authenticate(user=self.admin)
        fake_client = FakeListmonkClient()
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Draft subject",
            body_text="Draft body",
            mailing_list=self.mailing_list,
        )

        with patch("lanternmail.api.views.get_listmonk_client", return_value=fake_client):
            response = self.client.post(
                f"{self.posts_url}/{post.id}/test",
                data={"emails": ["test@example.com"]},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(fake_client.test_sends[0]["campaign_id"], 12345)
        self.assertEqual(fake_client.test_sends[0]["subscribers"], ["test@example.com"])

    def test_send_requires_ready_post(self):
        self.client.force_authenticate(user=self.admin)
        fake_client = FakeListmonkClient()
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Draft",
            subject="Draft subject",
            body_text="Draft body",
            mailing_list=self.mailing_list,
        )

        with patch("lanternmail.api.views.get_listmonk_client", return_value=fake_client):
            response = self.client.post(f"{self.posts_url}/{post.id}/send")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fake_client.status_updates, [])

    def test_send_ready_post_dispatches_and_marks_sent(self):
        self.client.force_authenticate(user=self.admin)
        fake_client = FakeListmonkClient()
        post = LanternmailPost.objects.create(
            group=self.group,
            created_by=self.admin,
            title="Ready",
            subject="Ready subject",
            body_text="Ready body",
            status=LanternmailPost.STATUS_READY,
            mailing_list=self.mailing_list,
        )

        with patch("lanternmail.api.views.get_listmonk_client", return_value=fake_client):
            response = self.client.post(f"{self.posts_url}/{post.id}/send")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post.refresh_from_db()
        self.assertEqual(post.status, LanternmailPost.STATUS_SENT)
        self.assertEqual(post.ingest_status, LanternmailPost.INGEST_ELIGIBLE)
        self.assertIsNotNone(post.sent_at)
        self.assertEqual(post.listmonk_campaign_id, 12345)
        self.assertEqual(fake_client.status_updates, [{"campaign_id": 12345, "status": "running"}])

    def test_create_post_from_lantern_placement_preserves_editable_copy_and_provenance(self):
        self.client.force_authenticate(user=self.admin)
        placement = self._create_lantern_placement(
            title="Harvest Note",
            body_text="Locked version body",
            overrides={"lantern_subject": "Harvest subject"},
        )

        response = self.client.post(
            f"{self.posts_url}/from-placement/{placement.id}",
            data={
                "mailing_list": self.mailing_list.id,
                "audience_kind": LanternmailPost.AUDIENCE_SUBSCRIBERS,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        post = LanternmailPost.objects.get(id=response.data["id"])
        self.assertEqual(post.title, "Harvest Note")
        self.assertEqual(post.subject, "Harvest subject")
        self.assertEqual(post.body_text, "Locked version body")
        self.assertEqual(post.status, LanternmailPost.STATUS_DRAFT)
        self.assertEqual(post.audience_kind, LanternmailPost.AUDIENCE_SUBSCRIBERS)
        self.assertEqual(post.mailing_list, self.mailing_list)
        self.assertEqual(post.content_placement, placement)
        self.assertEqual(post.publication_group, placement.publication_group)
        self.assertEqual(post.source_content_type, placement.source_content_type)
        self.assertEqual(post.source_object_id, str(placement.source_object_id))
        self.assertEqual(post.metadata["created_from"], "content_placement")

    def test_create_post_from_placement_is_idempotent(self):
        self.client.force_authenticate(user=self.admin)
        placement = self._create_lantern_placement()

        first = self.client.post(f"{self.posts_url}/from-placement/{placement.id}", format="json")
        second = self.client.post(f"{self.posts_url}/from-placement/{placement.id}", format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(LanternmailPost.objects.filter(content_placement=placement).count(), 1)

    def test_create_post_from_placement_rejects_non_lantern_channel(self):
        self.client.force_authenticate(user=self.admin)
        placement = self._create_lantern_placement(channel="feed")

        response = self.client.post(f"{self.posts_url}/from-placement/{placement.id}", format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only lantern placements", response.data["detail"])

    def test_create_post_from_placement_does_not_mutate_source_writing(self):
        self.client.force_authenticate(user=self.admin)
        placement = self._create_lantern_placement(title="Original Title", body_text="Original body")
        piece = placement.source
        original_piece_body = piece.body_json

        response = self.client.post(f"{self.posts_url}/from-placement/{placement.id}", format="json")
        post = LanternmailPost.objects.get(id=response.data["id"])
        patch_response = self.client.patch(
            f"{self.posts_url}/{post.id}",
            data={"title": "Email Title", "subject": "Email subject", "body_json": _body_json("Email body")},
            format="json",
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        piece.refresh_from_db()
        self.assertEqual(piece.title, "Original Title")
        self.assertEqual(piece.body_json, original_piece_body)

    def test_create_post_from_writing_creates_lantern_placement_and_post(self):
        self.client.force_authenticate(user=self.admin)
        piece = self._create_published_piece(title="Source Piece", body_text="Version body")

        response = self.client.post(
            f"{self.posts_url}/from-writing/{piece.id}",
            data={
                "mailing_list": self.mailing_list.id,
                "audience_kind": LanternmailPost.AUDIENCE_SUBSCRIBERS,
                "subject": "Custom subject",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        post = LanternmailPost.objects.get(id=response.data["id"])
        placement = post.content_placement
        self.assertIsNotNone(placement)
        self.assertEqual(placement.channel, "lantern")
        self.assertEqual(placement.source, piece)
        self.assertEqual(placement.target, self.group)
        self.assertEqual(placement.overrides["lantern_subject"], "Custom subject")
        self.assertEqual(post.title, "Source Piece")
        self.assertEqual(post.subject, "Custom subject")
        self.assertEqual(post.body_text, "Version body")
        self.assertEqual(post.mailing_list, self.mailing_list)

    def test_create_post_from_writing_reuses_existing_lantern_placement(self):
        self.client.force_authenticate(user=self.admin)
        placement = self._create_lantern_placement(overrides={"lantern_subject": "Existing subject"})
        piece = placement.source

        response = self.client.post(f"{self.posts_url}/from-writing/{piece.id}", format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        post = LanternmailPost.objects.get(id=response.data["id"])
        self.assertEqual(post.content_placement, placement)
        self.assertEqual(post.subject, "Existing subject")
        self.assertEqual(ContentPlacement.objects.filter(source_object_id=piece.id, channel="lantern").count(), 1)

    def test_create_post_from_writing_rejects_piece_from_other_group(self):
        self.client.force_authenticate(user=self.admin)
        other_group = _create_group(
            sponsor_user=self.admin,
            title="Other Group",
            slug="other-lantern-group",
        )
        piece = self._create_published_piece(group=other_group)

        response = self.client.post(f"{self.posts_url}/from-writing/{piece.id}", format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not belong", response.data["detail"])
