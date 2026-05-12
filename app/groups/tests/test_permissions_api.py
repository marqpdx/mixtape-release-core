from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership


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


class MemberRoleManageApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="roles_admin",
            email="roles_admin@test.com",
            password="testpass123",
        )
        self.target = User.objects.create_user(
            username="roles_target",
            email="roles_target@test.com",
            password="testpass123",
        )
        self.group = _create_group(
            sponsor_user=self.admin,
            title="Roles Group",
            slug="roles-group",
        )
        _create_membership(group=self.group, user=self.admin, roles=["admin"])
        self.target_membership = _create_membership(
            group=self.group,
            user=self.target,
            roles=["admin", "steward"],
        )

    def test_admin_can_revoke_member_role(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(
            f"/api/groups/{self.group.slug}/members/{self.target.id}/roles",
            data={"role": "admin"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.target_membership.refresh_from_db()
        self.assertNotIn("admin", self.target_membership.roles)
        self.assertIn("steward", self.target_membership.roles)
