from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models.dec_enums import AdmissionPolicy
from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership


User = get_user_model()


class PublicAdmissionStatusApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@test.com", password="pass")
        self.member = User.objects.create_user(username="member", email="member@test.com", password="pass")
        self.outsider = User.objects.create_user(username="outsider", email="outsider@test.com", password="pass")

        self.group = GroupService.create_group(
            title="Public Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
        )
        self.group.admission_policy = AdmissionPolicy.APPLICATION
        self.group.save(update_fields=["admission_policy"])

        ensure_user_membership(self.group, self.member, role="member")

        self.client = APIClient()

    def _status_url(self, slug):
        return f"/api/public/groups/{slug}/admission-status"

    def _detail_url(self, slug):
        return f"/api/public/groups/{slug}"

    def test_admission_status_anonymous(self):
        response = self.client.get(self._status_url(self.group.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["policy"], AdmissionPolicy.APPLICATION)
        self.assertFalse(response.data["can_join"])
        self.assertTrue(response.data["can_request"])

    def test_admission_status_authenticated_member(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self._status_url(self.group.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_member"])
        self.assertFalse(response.data["can_join"])

    def test_admission_status_nonexistent_group(self):
        response = self.client.get(self._status_url("does-not-exist"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admission_status_inactive_group(self):
        self.group.is_active = False
        self.group.save(update_fields=["is_active"])
        response = self.client.get(self._status_url(self.group.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_group_detail_includes_admission_policy(self):
        response = self.client.get(self._detail_url(self.group.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("admission_policy", response.data)
        self.assertEqual(response.data["admission_policy"], AdmissionPolicy.APPLICATION)
