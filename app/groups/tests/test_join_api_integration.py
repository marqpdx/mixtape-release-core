from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models.dec_enums import AdmissionPolicy
from groups.services.groups import GroupService


User = get_user_model()


class JoinApiIntegrationTests(TestCase):
    """Non-mocked regression coverage for producer/audience path in join flows."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner_int", email="owner_int@test.com", password="pass")
        self.joiner = User.objects.create_user(username="joiner_int", email="joiner_int@test.com", password="pass")
        self.requester = User.objects.create_user(
            username="requester_int", email="requester_int@test.com", password="pass"
        )
        self.client = APIClient()

    def test_join_open_group_without_moderators_does_not_500(self):
        group = GroupService.create_group(
            title="No Mods Open",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        group.admission_policy = AdmissionPolicy.OPEN
        group.save(update_fields=["admission_policy"])

        self.client.force_authenticate(self.joiner)
        response = self.client.post(f"/api/groups/{group.slug}/join", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_join_application_without_moderators_does_not_500(self):
        group = GroupService.create_group(
            title="No Mods App",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        group.admission_policy = AdmissionPolicy.APPLICATION
        group.save(update_fields=["admission_policy"])

        self.client.force_authenticate(self.requester)
        response = self.client.post(
            f"/api/groups/{group.slug}/request-join",
            {"message": "Please let me in"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("invitation_id", response.data)
