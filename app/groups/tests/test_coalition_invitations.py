from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from groups.models import Group, GroupInvitation, GroupMembership
from groups.models.group import InvitationKind, InvitationStatus


User = get_user_model()


class CoalitionInvitationFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_admin = User.objects.create_user(
            username="admin_user",
            email="admin@test.com",
            password="testpass123",
        )
        self.user_group_admin = User.objects.create_user(
            username="group_admin",
            email="group_admin@test.com",
            password="testpass123",
        )
        self.user_regular = User.objects.create_user(
            username="regular_user",
            email="regular@test.com",
            password="testpass123",
        )

        self.coalition = Group.objects.create(
            title="Test Coalition",
            slug="test-coalition",
            description="Coalition group",
            group_type="coalition",
            decorators=[],
            additional_permissions=[],
        )
        self.member_group = Group.objects.create(
            title="Member Group",
            slug="member-group",
            description="Group to be invited",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )

        user_ct = ContentType.objects.get_for_model(User)

        GroupMembership.objects.create(
            group=self.coalition,
            member_content_type=user_ct,
            member_object_id=self.user_admin.id,
            roles=["admin"],
            is_active=True,
            is_pending=False,
        )
        GroupMembership.objects.create(
            group=self.member_group,
            member_content_type=user_ct,
            member_object_id=self.user_group_admin.id,
            roles=["admin"],
            is_active=True,
            is_pending=False,
        )

    def test_coalition_invite_creates_group_invitation(self):
        self.client.force_authenticate(user=self.user_admin)
        response = self.client.post(
            f"/api/groups/{self.coalition.slug}/coalition-invitations/invite",
            {"invited_group_slug": self.member_group.slug, "message": "Join us"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        invitation = GroupInvitation.objects.get(id=response.data["id"])
        self.assertEqual(invitation.group, self.coalition)
        self.assertEqual(invitation.invited_group, self.member_group)
        self.assertEqual(invitation.invitation_kind, InvitationKind.INVITE)
        self.assertEqual(invitation.invitation_status, InvitationStatus.PENDING)

    def test_invited_group_can_accept_invitation(self):
        invitation = GroupInvitation.objects.create(
            group=self.coalition,
            invited_group=self.member_group,
            invited_by=self.user_admin,
            message="Join us",
            invitation_kind=InvitationKind.INVITE,
        )

        self.client.force_authenticate(user=self.user_group_admin)
        response = self.client.post(
            f"/api/groups/coalition-invitations/{invitation.id}/respond",
            {"action": "accept"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.invitation_status, InvitationStatus.JOINED)

        group_ct = ContentType.objects.get_for_model(Group)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=self.coalition,
                member_content_type=group_ct,
                member_object_id=self.member_group.id,
                is_active=True,
                is_pending=False,
            ).exists()
        )

    def test_group_can_request_to_join_coalition(self):
        self.client.force_authenticate(user=self.user_group_admin)
        response = self.client.post(
            f"/api/groups/{self.coalition.slug}/coalition-invitations/request",
            {"requesting_group_slug": self.member_group.slug, "message": "Please let us in"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        invitation = GroupInvitation.objects.get(id=response.data["id"])
        self.assertEqual(invitation.invitation_kind, InvitationKind.REQUEST)
        self.assertEqual(invitation.invitation_status, InvitationStatus.PENDING)

    def test_coalition_admin_can_accept_join_request(self):
        invitation = GroupInvitation.objects.create(
            group=self.coalition,
            invited_group=self.member_group,
            invited_by=self.user_group_admin,
            message="We want to join",
            invitation_kind=InvitationKind.REQUEST,
        )

        self.client.force_authenticate(user=self.user_admin)
        response = self.client.post(
            f"/api/groups/coalition-invitations/{invitation.id}/respond",
            {"action": "accept"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.invitation_status, InvitationStatus.JOINED)

    def test_request_requires_group_admin(self):
        self.client.force_authenticate(user=self.user_regular)
        response = self.client.post(
            f"/api/groups/{self.coalition.slug}/coalition-invitations/request",
            {"requesting_group_slug": self.member_group.slug},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_invite_rejected_for_non_coalition_group(self):
        community = Group.objects.create(
            title="Community",
            slug="community-group",
            description="Not a coalition",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        self.client.force_authenticate(user=self.user_admin)
        response = self.client.post(
            f"/api/groups/{community.slug}/coalition-invitations/invite",
            {"invited_group_slug": self.member_group.slug},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
