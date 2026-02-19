from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models.dec_enums import AdmissionPolicy
from groups.models.group import GroupInvitation, InvitationKind, InvitationStatus
from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership


User = get_user_model()


class JoinApiTests(TestCase):
    def setUp(self):
        self.member_joined_patcher = patch("groups.producers.on_member_joined")
        self.join_submitted_patcher = patch("groups.producers.on_join_request_submitted")
        self.join_responded_patcher = patch("groups.producers.on_join_request_responded")
        self.email_patcher = patch("groups.services.join_service.send_transactional_email_task.delay")
        self.member_joined_patcher.start()
        self.join_submitted_patcher.start()
        self.join_responded_patcher.start()
        self.email_patcher.start()
        self.addCleanup(self.member_joined_patcher.stop)
        self.addCleanup(self.join_submitted_patcher.stop)
        self.addCleanup(self.join_responded_patcher.stop)
        self.addCleanup(self.email_patcher.stop)

        self.owner = User.objects.create_user(username="owner", email="owner@test.com", password="pass")
        self.admin = User.objects.create_user(username="admin", email="admin@test.com", password="pass")
        self.member = User.objects.create_user(username="member", email="member@test.com", password="pass")
        self.outsider = User.objects.create_user(username="outsider", email="outsider@test.com", password="pass")

        self.group = GroupService.create_group(
            title="Join API Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
        )
        ensure_user_membership(self.group, self.admin, role="admin")
        ensure_user_membership(self.group, self.member, role="member")

        self.client = APIClient()

    def test_join_endpoint_success_and_unauthenticated_and_wrong_policy(self):
        open_group = GroupService.create_group(
            title="Open Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        open_group.admission_policy = AdmissionPolicy.OPEN
        open_group.save(update_fields=["admission_policy"])

        join_url = f"/api/groups/{open_group.slug}/join"

        unauth = self.client.post(join_url, {}, format="json")
        self.assertEqual(unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.outsider)
        ok = self.client.post(join_url, {}, format="json")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertEqual(ok.data["detail"], "Successfully joined group.")

        open_group.admission_policy = AdmissionPolicy.CLOSED
        open_group.save(update_fields=["admission_policy"])
        bad = self.client.post(join_url, {}, format="json")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_join_endpoint_success_with_message_and_unauthenticated(self):
        request_group = GroupService.create_group(
            title="Request Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        request_group.admission_policy = AdmissionPolicy.APPLICATION
        request_group.save(update_fields=["admission_policy"])

        url = f"/api/groups/{request_group.slug}/request-join"

        unauth = self.client.post(url, {}, format="json")
        self.assertEqual(unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.outsider)
        response = self.client.post(url, {"message": "Please"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        invitation = GroupInvitation.objects.get(id=response.data["invitation_id"])
        self.assertEqual(invitation.message, "Please")
        self.assertEqual(invitation.invitation_kind, InvitationKind.REQUEST)
        self.assertEqual(invitation.invitation_status, InvitationStatus.PENDING)

    def test_join_requests_admin_list_and_permissions(self):
        target = User.objects.create_user(username="applicant", email="applicant@test.com", password="pass")
        GroupInvitation.objects.create(
            group=self.group,
            invited_user=target,
            invited_by=target,
            invitation_kind=InvitationKind.REQUEST,
            invitation_status=InvitationStatus.PENDING,
        )
        url = f"/api/groups/{self.group.slug}/join-requests"

        unauth = self.client.get(url)
        self.assertEqual(unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.member)
        non_admin = self.client.get(url)
        self.assertEqual(non_admin.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.admin)
        ok = self.client.get(url)
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        payload = ok.data.get("results") if isinstance(ok.data, dict) else ok.data
        self.assertEqual(len(payload), 1)

    def test_respond_join_request_accept_decline_invalid_and_non_admin(self):
        requester = User.objects.create_user(username="requester", email="requester@test.com", password="pass")
        invitation = GroupInvitation.objects.create(
            group=self.group,
            invited_user=requester,
            invited_by=requester,
            invitation_kind=InvitationKind.REQUEST,
            invitation_status=InvitationStatus.PENDING,
        )

        url = f"/api/groups/{self.group.slug}/join-requests/{invitation.id}/respond"

        self.client.force_authenticate(self.member)
        denied = self.client.post(url, {"action": "accept"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.admin)
        invalid = self.client.post(url, {"action": "invalid"}, format="json")
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

        accept = self.client.post(url, {"action": "accept"}, format="json")
        self.assertEqual(accept.status_code, status.HTTP_200_OK)
        invitation.refresh_from_db()
        self.assertEqual(invitation.invitation_status, InvitationStatus.JOINED)

        user_ct = ContentType.objects.get_for_model(User)
        self.assertTrue(
            self.group.memberships.filter(
                member_content_type=user_ct,
                member_object_id=requester.id,
                is_active=True,
            ).exists()
        )

        requester2 = User.objects.create_user(username="requester2", email="requester2@test.com", password="pass")
        invitation2 = GroupInvitation.objects.create(
            group=self.group,
            invited_user=requester2,
            invited_by=requester2,
            invitation_kind=InvitationKind.REQUEST,
            invitation_status=InvitationStatus.PENDING,
        )
        url2 = f"/api/groups/{self.group.slug}/join-requests/{invitation2.id}/respond"
        decline = self.client.post(url2, {"action": "decline"}, format="json")
        self.assertEqual(decline.status_code, status.HTTP_200_OK)
        invitation2.refresh_from_db()
        self.assertEqual(invitation2.invitation_status, InvitationStatus.DECLINED)
