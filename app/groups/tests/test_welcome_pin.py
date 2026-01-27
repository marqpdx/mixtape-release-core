from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from publishing.models import ContentPlacement, PublicationGroup
from writing.models import WritingPiece, WritingVersion


User = get_user_model()


class GroupWelcomePinTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user(
            username="author",
            email="author@test.com",
            password="testpass123",
        )
        self.group_member = User.objects.create_user(
            username="member",
            email="member@test.com",
            password="testpass123",
        )
        self.community_member = User.objects.create_user(
            username="community",
            email="community@test.com",
            password="testpass123",
        )

        self.group = self._create_group(
            sponsor_user=self.author,
            title="Welcome Group",
            slug="welcome-group",
        )

        default_slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "") or "crossroads"
        self.default_group = self._create_group(
            sponsor_user=self.author,
            title="Default Community",
            slug=default_slug,
        )

        user_ct = ContentType.objects.get_for_model(User)
        GroupMembership.objects.create(
            group=self.group,
            member_content_type=user_ct,
            member_object_id=self.group_member.id,
            roles=["member"],
            is_active=True,
            is_pending=False,
        )
        GroupMembership.objects.create(
            group=self.default_group,
            member_content_type=user_ct,
            member_object_id=self.community_member.id,
            roles=["member"],
            is_active=True,
            is_pending=False,
        )

        self._create_welcome_pin(
            title="Group Welcome",
            slug="group-welcome",
            audience="group",
            visibility="members",
        )
        self._create_welcome_pin(
            title="Community Welcome",
            slug="community-welcome",
            audience="community",
            visibility="public",
        )
        self._create_welcome_pin(
            title="Public Welcome",
            slug="public-welcome",
            audience="public",
            visibility="public",
        )

        self._create_welcome_pin(
            title="Draft Welcome",
            slug="draft-welcome",
            audience="group",
            visibility="members",
            status="draft",
        )

    def _create_group(self, *, sponsor_user, title, slug):
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

    def _create_welcome_pin(self, title, slug, audience, visibility, status="published"):
        ct_group = ContentType.objects.get_for_model(Group)
        ct_piece = ContentType.objects.get_for_model(WritingPiece)

        piece = WritingPiece.objects.create(
            title=title,
            slug=slug,
            body_json={"type": "doc", "content": []},
            excerpt=f"{title} excerpt",
            writing_kind="post",
            status=status,
            published_at=timezone.now() if status == "published" else None,
            sponsor_content_type=ct_group,
            sponsor_object_id=self.group.id,
            author=self.author,
            author_name=self.author.username,
        )

        WritingVersion.objects.create(
            writing_piece=piece,
            version_number=1,
            body_json=piece.body_json,
            title=piece.title,
            excerpt=piece.excerpt,
            kind="release",
            created_by=self.author,
        )

        pub_group = PublicationGroup.objects.create(
            created_by=self.author,
            source_content_type=ct_piece,
            source_object_id=piece.id,
        )

        ContentPlacement.objects.create(
            publication_group=pub_group,
            placed_by=self.author,
            source_content_type=ct_piece,
            source_object_id=piece.id,
            target_content_type=ct_group,
            target_object_id=self.group.id,
            channel="feed",
            visibility=visibility,
            follow_updates=True,
            overrides={
                "pin_kind": "welcome",
                "pin_audience": audience,
            },
        )

    def test_group_member_sees_group_pin(self):
        self.client.force_authenticate(user=self.group_member)
        response = self.client.get(f"/api/groups/{self.group.slug}/welcome")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["audience"], "community")
        self.assertEqual(response.data["piece"]["title"], "Community Welcome")

    def test_default_community_member_sees_community_pin(self):
        self.client.force_authenticate(user=self.community_member)
        response = self.client.get(f"/api/groups/{self.group.slug}/welcome")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["audience"], "community")
        self.assertEqual(response.data["piece"]["title"], "Community Welcome")

    def test_anonymous_sees_public_pin(self):
        response = self.client.get(f"/api/groups/{self.group.slug}/welcome")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["audience"], "public")
        self.assertEqual(response.data["piece"]["title"], "Public Welcome")

    def test_unpublished_piece_is_ignored(self):
        self.client.force_authenticate(user=self.group_member)
        response = self.client.get(f"/api/groups/{self.group.slug}/welcome")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["audience"], "community")
        self.assertEqual(response.data["piece"]["title"], "Community Welcome")
