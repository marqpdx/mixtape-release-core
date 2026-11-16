from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from initiatives.models import (
    Initiative,
    InitiativeLog,
    InitiativeLogEntry,
    InitiativeLogEntryKind,
)


User = get_user_model()

STREAM_URL = "/api/worktable/stream/"
PROSE_URL = "/api/worktable/prose/"


class WorkTableInitiativeAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="wt_owner", email="wt_owner@example.com", password="testpass123"
        )
        self.other = User.objects.create_user(
            username="wt_other", email="wt_other@example.com", password="testpass123"
        )
        self.superuser = User.objects.create_superuser(
            username="wt_super", email="wt_super@example.com", password="testpass123"
        )
        self.user_ct = ContentType.objects.get_for_model(User)
        self.initiative = Initiative.objects.create(
            title="Owner's Initiative",
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.owner.id,
            created_by=self.owner,
        )
        self.log, _ = InitiativeLog.objects.get_or_create(initiative=self.initiative)
        InitiativeLogEntry.objects.create(
            initiative_log=self.log,
            kind=InitiativeLogEntryKind.PROSE,
            body="An entry in the owner's log.",
            authored_by=self.owner.username,
            created_by=self.owner,
            is_system_generated=False,
        )

    def _stream(self):
        return self.client.get(
            STREAM_URL, {"scope": "initiative", "initiative_id": str(self.initiative.id)}
        )

    def _prose(self, **extra):
        return self.client.post(PROSE_URL, {"body": "A new entry.", **extra}, format="json")

    # -- stream, initiative scope ------------------------------------------

    def test_sponsor_reads_initiative_stream(self):
        self.client.force_authenticate(self.owner)
        response = self._stream()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bodies = [e["body"] for e in response.data["entries"]]
        self.assertIn("An entry in the owner's log.", bodies)

    def test_other_member_is_refused_initiative_stream(self):
        self.client.force_authenticate(self.other)
        response = self._stream()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn("entries", response.data)

    def test_superuser_reads_initiative_stream(self):
        self.client.force_authenticate(self.superuser)
        self.assertEqual(self._stream().status_code, status.HTTP_200_OK)

    def test_refusal_matches_unknown_initiative(self):
        self.client.force_authenticate(self.other)
        refused = self._stream()
        unknown = self.client.get(
            STREAM_URL,
            {"scope": "initiative", "initiative_id": "00000000-0000-4000-8000-000000000000"},
        )
        self.assertEqual(refused.status_code, unknown.status_code)

    # -- prose -------------------------------------------------------------

    def test_sponsor_writes_prose_to_initiative(self):
        self.client.force_authenticate(self.owner)
        response = self._prose(initiative_id=str(self.initiative.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.log.entries.count(), 2)

    def test_other_member_is_refused_prose_and_nothing_is_written(self):
        self.client.force_authenticate(self.other)
        response = self._prose(initiative_id=str(self.initiative.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.log.entries.count(), 1)

    def test_prose_without_initiative_goes_to_own_personal_initiative(self):
        self.client.force_authenticate(self.other)
        response = self._prose()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        personal = Initiative.objects.get(
            is_personal=True,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.other.id,
        )
        self.assertEqual(personal.initiative_log.entries.count(), 1)
        self.assertEqual(self.log.entries.count(), 1)

    # -- the older log route keeps the same rule ----------------------------

    def test_log_route_rule_is_unchanged(self):
        url = f"/api/initiatives/{self.initiative.id}/log"
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    # -- malformed initiative_id is a 400, not a 500 ------------------------

    def test_stream_rejects_malformed_initiative_id(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(
            STREAM_URL, {"scope": "initiative", "initiative_id": "not-a-uuid"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_prose_rejects_malformed_initiative_id_and_writes_nothing(self):
        self.client.force_authenticate(self.owner)
        response = self._prose(initiative_id="not-a-uuid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertEqual(self.log.entries.count(), 1)
        self.assertFalse(
            Initiative.objects.filter(
                is_personal=True,
                sponsor_content_type=self.user_ct,
                sponsor_object_id=self.owner.id,
            ).exists()
        )
