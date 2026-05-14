from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.services.groups import GroupService
from initiatives.models import (
    ApertureLog,
    Initiative,
    InitiativeStatus,
    Session,
)


User = get_user_model()


class GroupInitiativesApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_superuser(
            username="initiative_super",
            email="initiative_super@example.com",
            password="testpass123",
        )
        self.member = User.objects.create_user(
            username="initiative_member",
            email="initiative_member@example.com",
            password="testpass123",
        )
        self.group = GroupService.create_group(
            title="Initiatives Group",
            group_type="community",
            created_by=self.superuser,
            visibility="public",
            slug="initiatives-group",
        )
        self.group_ct = ContentType.objects.get_for_model(self.group)
        self.base_url = f"/api/groups/{self.group.slug}/initiatives"

    def _create_initiative(self, **overrides):
        data = {
            "title": "Default Initiative",
            "direction": "Explore the problem space",
            "status": InitiativeStatus.ACTIVE,
            "sponsor_content_type": self.group_ct,
            "sponsor_object_id": self.group.id,
            "created_by": self.superuser,
        }
        data.update(overrides)
        return Initiative.objects.create(**data)

    def test_initiative_list_requires_authentication(self):
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_initiative_list_and_create_require_superuser(self):
        self.client.force_authenticate(self.member)

        list_response = self.client.get(self.base_url)
        create_response = self.client.post(
            self.base_url,
            {"title": "Blocked Initiative", "direction": "No access"},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_create_initiative_sets_defaults_and_aperture_log(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            self.base_url,
            {
                "title": "Create Initiative",
                "direction": "Investigate a new path",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        initiative = Initiative.objects.get(title="Create Initiative")
        self.assertEqual(initiative.created_by, self.superuser)
        self.assertEqual(
            response.data["rolling_summary"],
            {
                "current_direction": "",
                "key_decisions": [],
                "open_questions": [],
                "where_we_are_now": "",
            },
        )
        self.assertTrue(ApertureLog.objects.filter(initiative=initiative).exists())

    def test_superuser_list_hides_resolved_and_archived_by_default(self):
        active = self._create_initiative(title="Active Initiative", status=InitiativeStatus.ACTIVE)
        resolved = self._create_initiative(title="Resolved Initiative", status=InitiativeStatus.RESOLVED)
        archived = self._create_initiative(title="Archived Initiative", status=InitiativeStatus.ARCHIVED)

        self.client.force_authenticate(self.superuser)

        response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data}
        self.assertIn(str(active.id), ids)
        self.assertNotIn(str(resolved.id), ids)
        self.assertNotIn(str(archived.id), ids)

    def test_superuser_list_include_resolved_shows_resolved_and_archived(self):
        active = self._create_initiative(title="Active Initiative", status=InitiativeStatus.ACTIVE)
        resolved = self._create_initiative(title="Resolved Initiative", status=InitiativeStatus.RESOLVED)
        archived = self._create_initiative(title="Archived Initiative", status=InitiativeStatus.ARCHIVED)

        self.client.force_authenticate(self.superuser)

        response = self.client.get(f"{self.base_url}?include_resolved=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data}
        self.assertIn(str(active.id), ids)
        self.assertIn(str(resolved.id), ids)
        self.assertIn(str(archived.id), ids)

    def test_superuser_can_patch_and_delete_initiative(self):
        initiative = self._create_initiative(title="Original Title")
        self.client.force_authenticate(self.superuser)

        patch_response = self.client.patch(
            f"{self.base_url}/{initiative.id}",
            {"title": "Updated Title", "status_note": "Paused for review"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["title"], "Updated Title")
        self.assertEqual(patch_response.data["status_note"], "Paused for review")

        delete_response = self.client.delete(f"{self.base_url}/{initiative.id}")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        initiative.refresh_from_db()
        self.assertIsNotNone(initiative.deleted_at)

    def test_rolling_summary_patch_merges_fields_and_tracks_editor(self):
        initiative = self._create_initiative(
            rolling_summary={
                "current_direction": "Initial direction",
                "key_decisions": ["Keep scope narrow"],
                "open_questions": [],
                "where_we_are_now": "Starting point",
            }
        )
        self.client.force_authenticate(self.superuser)

        response = self.client.patch(
            f"{self.base_url}/{initiative.id}/rolling-summary",
            {
                "open_questions": ["What evidence do we need?"],
                "where_we_are_now": "Reviewing current inputs",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        initiative.refresh_from_db()
        self.assertEqual(
            response.data["rolling_summary"],
            {
                "current_direction": "Initial direction",
                "key_decisions": ["Keep scope narrow"],
                "open_questions": ["What evidence do we need?"],
                "where_we_are_now": "Reviewing current inputs",
            },
        )
        self.assertEqual(initiative.rolling_summary_updated_by, self.superuser.username)
        self.assertIsNotNone(initiative.rolling_summary_updated_at)

    def test_superuser_can_create_and_list_sessions_with_defaults(self):
        initiative = self._create_initiative()
        self.client.force_authenticate(self.superuser)
        sessions_url = f"{self.base_url}/{initiative.id}/sessions"

        create_response = self.client.post(
            sessions_url,
            {"intent": "focused_review", "capture_mode": "typed"},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        session = Session.objects.get(id=create_response.data["id"])
        self.assertEqual(session.initiative, initiative)
        self.assertEqual(session.created_by, self.superuser)
        self.assertEqual(session.raw_transcript, [])
        self.assertEqual(session.distillation, {})

        list_response = self.client.get(sessions_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["id"], str(session.id))

    def test_session_create_requires_valid_payload(self):
        initiative = self._create_initiative()
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            f"{self.base_url}/{initiative.id}/sessions",
            {"intent": "not-a-valid-choice"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
