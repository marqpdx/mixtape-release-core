from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from identity.models import EmblemAvatar, EmblemAvatarType


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


def _create_emblem_type(*, engine: str = "initials", style: str = "rounded") -> EmblemAvatarType:
    return EmblemAvatarType.objects.create(
        engine=engine,
        style=style,
        label=f"{engine}:{style}",
        is_upload=False,
        is_generator=True,
        supports_fg=True,
        supports_bg=True,
        supports_initials=True,
    )


def _create_emblem(*, sponsor: User, emblem_type: EmblemAvatarType, reuse_policy: str) -> EmblemAvatar:
    emblem = EmblemAvatar(
        title="Test Emblem",
        type=emblem_type,
        reuse_policy=reuse_policy,
        seed="seed",
        size_96="https://example.com/emblems/size_96.png",
    )
    emblem.set_sponsor(sponsor)
    emblem.set_submitted_by(sponsor)
    emblem.author = sponsor
    emblem.author_name = sponsor.get_full_name() or sponsor.username
    emblem.save()
    return emblem


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


class GroupEmblemAttachTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_admin = User.objects.create_user(
            username="emblem_admin",
            email="emblem_admin@test.com",
            password="testpass123",
        )
        self.user_steward = User.objects.create_user(
            username="emblem_steward",
            email="emblem_steward@test.com",
            password="testpass123",
        )
        self.user_member = User.objects.create_user(
            username="emblem_member",
            email="emblem_member@test.com",
            password="testpass123",
        )
        self.user_outsider = User.objects.create_user(
            username="emblem_outsider",
            email="emblem_outsider@test.com",
            password="testpass123",
        )

        self.group = _create_group(
            sponsor_user=self.user_admin,
            title="Emblem Group",
            slug="emblem-group",
        )

        _create_membership(group=self.group, user=self.user_admin, roles=["admin"])
        _create_membership(group=self.group, user=self.user_steward, roles=["steward"])
        _create_membership(group=self.group, user=self.user_member, roles=["member"])

        self.emblem_type = _create_emblem_type()
        self.emblem = _create_emblem(
            sponsor=self.user_admin,
            emblem_type=self.emblem_type,
            reuse_policy=EmblemAvatar.REUSE_ANYONE,
        )

    def test_admin_can_attach_emblem(self):
        self.client.force_authenticate(user=self.user_admin)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.emblem_id, self.emblem.id)
        self.assertEqual(response.data["emblem"]["id"], str(self.emblem.id))

    def test_steward_can_attach_emblem(self):
        self.client.force_authenticate(user=self.user_steward)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.emblem_id, self.emblem.id)

    def test_member_cannot_attach_emblem(self):
        self.client.force_authenticate(user=self.user_member)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_cannot_attach_emblem(self):
        self.client.force_authenticate(user=self.user_outsider)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class GroupEmblemResetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_admin = User.objects.create_user(
            username="reset_admin",
            email="reset_admin@test.com",
            password="testpass123",
        )
        self.user_member = User.objects.create_user(
            username="reset_member",
            email="reset_member@test.com",
            password="testpass123",
        )
        self.user_outsider = User.objects.create_user(
            username="reset_outsider",
            email="reset_outsider@test.com",
            password="testpass123",
        )

        self.group = _create_group(
            sponsor_user=self.user_admin,
            title="Reset Group",
            slug="reset-group",
        )
        _create_membership(group=self.group, user=self.user_admin, roles=["admin"])
        _create_membership(group=self.group, user=self.user_member, roles=["member"])

        self.emblem_type = _create_emblem_type(engine="initials", style="square")
        self.emblem = _create_emblem(
            sponsor=self.user_admin,
            emblem_type=self.emblem_type,
            reuse_policy=EmblemAvatar.REUSE_ANYONE,
        )
        self.group.emblem = self.emblem
        self.group.save(update_fields=["emblem"])

    def test_admin_can_reset_emblem(self):
        self.client.force_authenticate(user=self.user_admin)
        response = self.client.post(f"/api/groups/{self.group.slug}/emblem/reset")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertIsNone(self.group.emblem_id)

    def test_member_cannot_reset_emblem(self):
        self.client.force_authenticate(user=self.user_member)
        response = self.client.post(f"/api/groups/{self.group.slug}/emblem/reset")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_cannot_reset_emblem(self):
        self.client.force_authenticate(user=self.user_outsider)
        response = self.client.post(f"/api/groups/{self.group.slug}/emblem/reset")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EmblemReusePolicyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="emblem_owner",
            email="emblem_owner@test.com",
            password="testpass123",
        )
        self.admin = User.objects.create_user(
            username="emblem_admin2",
            email="emblem_admin2@test.com",
            password="testpass123",
        )

        self.group = _create_group(
            sponsor_user=self.owner,
            title="Policy Group",
            slug="policy-group",
        )
        _create_membership(group=self.group, user=self.owner, roles=["admin"])
        _create_membership(group=self.group, user=self.admin, roles=["admin"])

        self.emblem_type = _create_emblem_type(engine="initials", style="circle")
        self.owner_only_emblem = _create_emblem(
            sponsor=self.owner,
            emblem_type=self.emblem_type,
            reuse_policy=EmblemAvatar.REUSE_OWNER_ONLY,
        )

    def test_non_owner_admin_cannot_attach_owner_only_emblem(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.owner_only_emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_attach_owner_only_emblem(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f"/api/groups/{self.group.slug}/emblem/attach",
            data={"emblem_id": str(self.owner_only_emblem.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group.refresh_from_db()
        self.assertEqual(self.group.emblem_id, self.owner_only_emblem.id)


class GroupEmblemSerializerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="serializer_user",
            email="serializer@test.com",
            password="testpass123",
        )

        self.emblem_type = _create_emblem_type(engine="initials", style="rounded")
        self.emblem = _create_emblem(
            sponsor=self.user,
            emblem_type=self.emblem_type,
            reuse_policy=EmblemAvatar.REUSE_ANYONE,
        )

        self.group_with_emblem = _create_group(
            sponsor_user=self.user,
            title="Group With Emblem",
            slug="group-with-emblem",
        )
        self.group_with_emblem.emblem = self.emblem
        self.group_with_emblem.save(update_fields=["emblem"])

        self.group_without_emblem = _create_group(
            sponsor_user=self.user,
            title="Group Without Emblem",
            slug="group-without-emblem",
        )

    def test_group_detail_includes_emblem(self):
        response = self.client.get(f"/api/groups/{self.group_with_emblem.slug}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["emblem"]["id"], str(self.emblem.id))
        self.assertTrue(response.data["emblem"]["size_96_url"] or response.data["emblem"]["url"])

        response = self.client.get(f"/api/groups/{self.group_without_emblem.slug}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["emblem"])

    def test_group_list_includes_emblem(self):
        response = self.client.get("/api/groups/?limit=50")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", [])
        by_slug = {item["slug"]: item for item in results}

        with_emblem = by_slug[self.group_with_emblem.slug]
        self.assertEqual(with_emblem["emblem"]["id"], str(self.emblem.id))
        self.assertTrue(with_emblem["emblem"]["size_96_url"] or with_emblem["emblem"]["url"])

        without_emblem = by_slug[self.group_without_emblem.slug]
        self.assertIsNone(without_emblem["emblem"])
