from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from lanternmail.models import LanternmailList, LanternmailPost


User = get_user_model()


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

    def test_admin_can_create_and_list_posts(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.posts_url,
            data={
                "title": "September Note",
                "subject": "A September note",
                "body": "Hello from LanternMail.",
                "audience_kind": "subscribers",
                "mailing_list": self.mailing_list.id,
                "metadata": {"origin": "test"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "September Note")
        self.assertEqual(response.data["status"], LanternmailPost.STATUS_DRAFT)
        self.assertNotIn("listmonk_campaign_id", response.data)
        self.assertNotIn("sent_at", response.data)
        self.assertNotIn("ingest_status", response.data)

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

    def test_phase_one_blocks_sent_transition(self):
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
        self.assertIn("Phase 1", response.data["error"])

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
