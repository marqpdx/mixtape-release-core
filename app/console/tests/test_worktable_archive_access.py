import uuid

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


def _archive_url(entry_id):
    return f"/api/worktable/entries/{entry_id}/archive/"


class WorkTableArchiveAccessTests(TestCase):
    """POST /api/worktable/entries/<id>/archive/ follows the Initiative's rule."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="wta_owner", email="wta_owner@example.com", password="testpass123"
        )
        self.other = User.objects.create_user(
            username="wta_other", email="wta_other@example.com", password="testpass123"
        )
        self.superuser = User.objects.create_superuser(
            username="wta_super", email="wta_super@example.com", password="testpass123"
        )
        user_ct = ContentType.objects.get_for_model(User)
        self.initiative = Initiative.objects.create(
            title="Owner's Initiative",
            sponsor_content_type=user_ct,
            sponsor_object_id=self.owner.id,
            created_by=self.owner,
        )
        self.log, _ = InitiativeLog.objects.get_or_create(initiative=self.initiative)
        self.system_entry = InitiativeLogEntry.objects.create(
            initiative_log=self.log,
            kind=InitiativeLogEntryKind.PROSE,
            body="A system-generated entry.",
            authored_by="system",
            created_by=None,
            is_system_generated=True,
        )
        self.ordinary_entry = InitiativeLogEntry.objects.create(
            initiative_log=self.log,
            kind=InitiativeLogEntryKind.PROSE,
            body="An entry the owner wrote.",
            authored_by=self.owner.username,
            created_by=self.owner,
            is_system_generated=False,
        )

    def _archive(self, entry_id):
        return self.client.post(_archive_url(entry_id))

    def _assert_unarchived(self, entry):
        entry.refresh_from_db()
        self.assertIsNone(entry.archived_at)

    # -- refusals ----------------------------------------------------------

    def test_other_member_is_refused_system_entry(self):
        self.client.force_authenticate(self.other)
        response = self._archive(self.system_entry.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self._assert_unarchived(self.system_entry)

    def test_other_member_is_refused_ordinary_entry(self):
        self.client.force_authenticate(self.other)
        response = self._archive(self.ordinary_entry.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self._assert_unarchived(self.ordinary_entry)

    def test_refusals_match_unknown_id(self):
        self.client.force_authenticate(self.other)
        unknown = self._archive(uuid.uuid4())
        for entry in (self.system_entry, self.ordinary_entry):
            refused = self._archive(entry.id)
            self.assertEqual(refused.status_code, unknown.status_code)
            self.assertEqual(refused.data, unknown.data)

    # -- the paths that work today still work -------------------------------

    def test_owner_archives_system_entry(self):
        self.client.force_authenticate(self.owner)
        response = self._archive(self.system_entry.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.system_entry.refresh_from_db()
        self.assertIsNotNone(self.system_entry.archived_at)

    def test_author_archives_own_entry(self):
        self.client.force_authenticate(self.owner)
        response = self._archive(self.ordinary_entry.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ordinary_entry.refresh_from_db()
        self.assertIsNotNone(self.ordinary_entry.archived_at)

    def test_superuser_archives_system_entry(self):
        self.client.force_authenticate(self.superuser)
        response = self._archive(self.system_entry.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.system_entry.refresh_from_db()
        self.assertIsNotNone(self.system_entry.archived_at)
