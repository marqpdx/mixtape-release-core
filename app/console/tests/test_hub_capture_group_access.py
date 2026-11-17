from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from console.models import HubCapture
from groups.models import Group, GroupMembership


User = get_user_model()

CAPTURES_URL = "/api/console/hub/captures/"
VOICE_URL = "/api/console/hub/captures/voice/"


class HubCaptureGroupAccessTests(TestCase):
    """Capture writes to a group need the caller to be a member of it."""

    def setUp(self):
        self.client = APIClient()
        self.member = User.objects.create_user(username="hc_member", password="testpass123")
        self.stranger = User.objects.create_user(username="hc_stranger", password="testpass123")
        user_ct = ContentType.objects.get_for_model(User)
        self.group = Group.objects.create(
            title="Capture Access", slug="capture-access", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=user_ct, sponsor_object_id=self.member.pk,
        )
        GroupMembership.objects.create(
            group=self.group, member_content_type=user_ct,
            member_object_id=self.member.pk, roles=["member"],
            is_active=True, is_pending=False,
        )

    def _capture(self, slug):
        return self.client.post(
            CAPTURES_URL,
            {"kind": "note", "body": "A note.", "group_slug": slug, "visibility": "shared"},
            format="json",
        )

    def _voice(self, slug):
        audio = SimpleUploadedFile("note.m4a", b"not really audio", content_type="audio/mp4")
        return self.client.post(VOICE_URL, {"audio": audio, "group_slug": slug}, format="multipart")

    # -- text captures ------------------------------------------------------

    def test_member_writes_capture_to_group(self):
        self.client.force_authenticate(self.member)
        response = self._capture(self.group.slug)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["group_id"], str(self.group.id))

    def test_stranger_is_refused_and_nothing_is_written(self):
        self.client.force_authenticate(self.stranger)
        response = self._capture(self.group.slug)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(HubCapture.objects.filter(owner=self.stranger).exists())

    def test_refusal_matches_unknown_slug(self):
        self.client.force_authenticate(self.stranger)
        refused = self._capture(self.group.slug)
        unknown = self._capture("no-such-group")
        self.assertEqual(refused.status_code, unknown.status_code)
        self.assertEqual(refused.data, unknown.data)

    def test_capture_without_group_is_unchanged(self):
        self.client.force_authenticate(self.stranger)
        response = self._capture(None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["group_id"])

    # -- voice captures -----------------------------------------------------

    def test_stranger_voice_is_refused_and_nothing_is_written(self):
        self.client.force_authenticate(self.stranger)
        refused = self._voice(self.group.slug)
        unknown = self._voice("no-such-group")
        self.assertEqual(refused.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(refused.data, unknown.data)
        self.assertFalse(HubCapture.objects.filter(owner=self.stranger).exists())
