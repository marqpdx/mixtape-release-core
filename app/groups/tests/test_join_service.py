from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from groups.models.dec_enums import AdmissionPolicy
from groups.models.group import GroupInvitation, InvitationKind, InvitationStatus
from groups.services.groups import GroupService
from groups.services.join_service import (
    get_admission_status,
    join_group,
    request_to_join_group,
    respond_to_join_request,
)
from groups.services.memberships import ensure_user_membership


User = get_user_model()


class JoinServiceTests(TestCase):
    def setUp(self):
        self.member_joined_patcher = patch("groups.producers.on_member_joined")
        self.join_submitted_patcher = patch("groups.producers.on_join_request_submitted")
        self.join_responded_patcher = patch("groups.producers.on_join_request_responded")
        self.email_patcher = patch("groups.services.join_service.send_transactional_email_task.delay")
        self.mock_member_joined = self.member_joined_patcher.start()
        self.mock_join_submitted = self.join_submitted_patcher.start()
        self.mock_join_responded = self.join_responded_patcher.start()
        self.mock_send_email = self.email_patcher.start()
        self.addCleanup(self.member_joined_patcher.stop)
        self.addCleanup(self.join_submitted_patcher.stop)
        self.addCleanup(self.join_responded_patcher.stop)
        self.addCleanup(self.email_patcher.stop)

        self.owner = User.objects.create_user(username="owner", email="owner@test.com", password="pass")
        self.user = User.objects.create_user(username="member", email="member@test.com", password="pass")
        self.other = User.objects.create_user(username="other", email="other@test.com", password="pass")
        self.parent_member = User.objects.create_user(
            username="parentmember", email="parentmember@test.com", password="pass"
        )

        self.parent_group = GroupService.create_group(
            title="Parent Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
        )
        self.group = GroupService.create_group(
            title="Child Group",
            group_type="circle",
            created_by=self.owner,
            visibility="public",
            sponsor=self.parent_group,
            add_creator_membership=False,
        )

        ensure_user_membership(self.group, self.owner, role="admin")
        ensure_user_membership(self.parent_group, self.parent_member, role="member")

    def test_join_open_group(self):
        self.group.admission_policy = AdmissionPolicy.OPEN
        self.group.save(update_fields=["admission_policy"])

        membership = join_group(self.group, self.user)
        self.assertTrue(membership.is_active)
        self.assertIn("member", membership.roles)
        self.mock_member_joined.assert_called_once()

    def test_join_open_parent_members_requires_parent_membership(self):
        self.group.admission_policy = AdmissionPolicy.OPEN_PARENT_MEMBERS
        self.group.save(update_fields=["admission_policy"])

        membership = join_group(self.group, self.parent_member)
        self.assertTrue(membership.is_active)

        with self.assertRaises(ValidationError):
            join_group(self.group, self.user)

    def test_join_rejects_disallowed_policies_and_existing_member(self):
        for policy in [AdmissionPolicy.APPLICATION, AdmissionPolicy.INVITE_ONLY, AdmissionPolicy.CLOSED]:
            self.group.admission_policy = policy
            self.group.save(update_fields=["admission_policy"])
            with self.assertRaises(ValidationError):
                join_group(self.group, self.user)

        self.group.admission_policy = AdmissionPolicy.OPEN
        self.group.save(update_fields=["admission_policy"])
        join_group(self.group, self.user)
        with self.assertRaises(ValidationError):
            join_group(self.group, self.user)

    def test_request_to_join_application_with_message_and_email(self):
        self.group.admission_policy = AdmissionPolicy.APPLICATION
        self.group.save(update_fields=["admission_policy"])

        invitation = request_to_join_group(self.group, self.user, message="Please let me in")
        self.assertEqual(invitation.invitation_kind, InvitationKind.REQUEST)
        self.assertEqual(invitation.invitation_status, InvitationStatus.PENDING)
        self.assertEqual(invitation.message, "Please let me in")
        self.mock_join_submitted.assert_called_once()
        self.mock_send_email.assert_called_once()

        with self.assertRaises(ValidationError):
            request_to_join_group(self.group, self.user)

    def test_request_parent_members_policy_and_open_policy_reject(self):
        self.group.admission_policy = AdmissionPolicy.APPLICATION_PARENT_MEMBERS
        self.group.save(update_fields=["admission_policy"])

        invitation = request_to_join_group(self.group, self.parent_member)
        self.assertEqual(invitation.invitation_status, InvitationStatus.PENDING)

        with self.assertRaises(ValidationError):
            request_to_join_group(self.group, self.user)

        self.group.admission_policy = AdmissionPolicy.OPEN
        self.group.save(update_fields=["admission_policy"])
        with self.assertRaises(ValidationError):
            request_to_join_group(self.group, self.other)

    def test_respond_to_join_request_accept_and_decline(self):
        self.group.admission_policy = AdmissionPolicy.APPLICATION
        self.group.save(update_fields=["admission_policy"])

        invitation = request_to_join_group(self.group, self.user)
        membership = respond_to_join_request(invitation, self.owner, "accept")
        invitation.refresh_from_db()
        self.assertEqual(invitation.invitation_status, InvitationStatus.JOINED)
        self.assertIsNotNone(membership)

        invite2 = request_to_join_group(self.group, self.other)
        result = respond_to_join_request(invite2, self.owner, "decline")
        invite2.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(invite2.invitation_status, InvitationStatus.DECLINED)

        self.assertEqual(self.mock_join_responded.call_count, 2)

    def test_respond_invalid_cases(self):
        self.group.admission_policy = AdmissionPolicy.APPLICATION
        self.group.save(update_fields=["admission_policy"])

        invitation = request_to_join_group(self.group, self.user)
        with self.assertRaises(ValidationError):
            respond_to_join_request(invitation, self.owner, "nope")

        invitation.invitation_kind = InvitationKind.INVITE
        invitation.save(update_fields=["invitation_kind"])
        with self.assertRaises(ValidationError):
            respond_to_join_request(invitation, self.owner, "accept")

    def test_get_admission_status_variants(self):
        self.group.admission_policy = AdmissionPolicy.OPEN
        self.group.save(update_fields=["admission_policy"])
        anon_open = get_admission_status(self.group, None)
        self.assertTrue(anon_open["can_join"])
        self.assertFalse(anon_open["is_member"])

        self.group.admission_policy = AdmissionPolicy.APPLICATION
        self.group.save(update_fields=["admission_policy"])
        anon_application = get_admission_status(self.group, None)
        self.assertTrue(anon_application["can_request"])

        self.group.admission_policy = AdmissionPolicy.CLOSED
        self.group.save(update_fields=["admission_policy"])
        anon_closed = get_admission_status(self.group, None)
        self.assertFalse(anon_closed["can_join"])
        self.assertFalse(anon_closed["can_request"])

        self.group.admission_policy = AdmissionPolicy.OPEN_PARENT_MEMBERS
        self.group.save(update_fields=["admission_policy"])
        status_parent_member = get_admission_status(self.group, self.parent_member)
        status_non_parent_member = get_admission_status(self.group, self.user)
        self.assertTrue(status_parent_member["can_join"])
        self.assertFalse(status_non_parent_member["can_join"])
        self.assertTrue(status_parent_member["requires_parent_membership"])
        self.assertEqual(status_parent_member["parent_group"]["slug"], self.parent_group.slug)

        ensure_user_membership(self.group, self.user, role="admin")
        member_status = get_admission_status(self.group, self.user)
        self.assertTrue(member_status["is_member"])
        self.assertTrue(member_status["is_moderator"])
