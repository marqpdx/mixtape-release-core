# concord/tests/test_recording_api.py

import uuid
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from concord.models import Recording, RecordingStatus
from groups.models import Group


User = get_user_model()


class ConcordRecordingAPITests(APITestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.storage_override = override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": self.temp_dir.name},
                },
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                },
            }
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)

        self.user = User.objects.create_user(
            username="concord-user",
            email="concord@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

        self.group = Group.objects.create(
            title="Concord Group",
            slug="concord-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        self.group_ct = ContentType.objects.get_for_model(Group)

    def _make_audio(self, name="test.mp3", content_type="audio/mpeg", content=b"fake audio"):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def _create_recording(self, **kwargs):
        return Recording.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            title=kwargs.get("title", "Test Recording"),
            summary=kwargs.get("summary", ""),
            body=kwargs.get("body", ""),
            submitted_by=self.user,
            status=kwargs.get("status", RecordingStatus.UPLOADED),
        )

    def test_endpoints_require_auth(self):
        recording = self._create_recording()
        client = APIClient()

        list_response = client.get("/api/concord/recordings/")
        self.assertEqual(list_response.status_code, status.HTTP_401_UNAUTHORIZED)

        create_response = client.post(
            "/api/concord/recordings/",
            data={"sponsor_type": "group", "sponsor_id": str(self.group.id)},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_401_UNAUTHORIZED)

        detail_response = client.get(f"/api/concord/recordings/{recording.id}/")
        self.assertEqual(detail_response.status_code, status.HTTP_401_UNAUTHORIZED)

        upload_response = client.post(
            f"/api/concord/recordings/{recording.id}/upload/",
            data={"file": self._make_audio()},
            format="multipart",
        )
        self.assertEqual(upload_response.status_code, status.HTTP_401_UNAUTHORIZED)

        transition_response = client.post(
            f"/api/concord/recordings/{recording.id}/transition/",
            data={"status": RecordingStatus.TRANSCRIBING},
            format="json",
        )
        self.assertEqual(transition_response.status_code, status.HTTP_401_UNAUTHORIZED)

        group_list_response = client.get(f"/api/concord/groups/{self.group.slug}/recordings/")
        self.assertEqual(group_list_response.status_code, status.HTTP_401_UNAUTHORIZED)

        group_create_response = client.post(
            f"/api/concord/groups/{self.group.slug}/recordings/create/",
            data={"title": "Test"},
            format="json",
        )
        self.assertEqual(group_create_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_requires_sponsor_params(self):
        response = self.client.get("/api/concord/recordings/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get("/api/concord/recordings/?sponsor_type=group")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(f"/api/concord/recordings/?sponsor_id={self.group.id}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_filters_by_status(self):
        self._create_recording(status=RecordingStatus.UPLOADED)
        self._create_recording(status=RecordingStatus.READY)

        response = self.client.get(
            f"/api/concord/recordings/?sponsor_type=group&sponsor_id={self.group.id}&status=uploaded"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["recordings"][0]["status"], RecordingStatus.UPLOADED)

    def test_list_invalid_sponsor_type(self):
        response = self.client.get(
            f"/api/concord/recordings/?sponsor_type=invalid&sponsor_id={self.group.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_recording_minimal(self):
        response = self.client.post(
            "/api/concord/recordings/",
            data={"sponsor_type": "group", "sponsor_id": str(self.group.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], RecordingStatus.UPLOADED)
        self.assertEqual(response.data["sponsor_type"], "group")
        self.assertEqual(response.data["sponsor_id"], str(self.group.id))

        recording = Recording.objects.get(id=response.data["id"])
        self.assertEqual(recording.submitted_by_id, self.user.id)

    def test_create_recording_with_file(self):
        payload = {
            "sponsor_type": "group",
            "sponsor_id": str(self.group.id),
            "title": "File Upload",
            "file": self._make_audio(),
        }
        response = self.client.post(
            "/api/concord/recordings/",
            data=payload,
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        recording = Recording.objects.get(id=response.data["id"])
        self.assertTrue(recording.audio_path)
        self.assertEqual(recording.audio_content_type, "audio/mpeg")
        self.assertEqual(recording.audio_size_bytes, len(b"fake audio"))
        expected_prefix = f"recordings/group/{self.group.id}/{recording.id}/"
        self.assertTrue(recording.audio_path.startswith(expected_prefix))

    def test_create_recording_invalid_sponsor(self):
        response = self.client.post(
            "/api/concord/recordings/",
            data={"sponsor_type": "group", "sponsor_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sponsor_id", response.data)

    def test_update_recording_fields(self):
        recording = self._create_recording(title="Old", summary="Old summary", body="Old body")
        response = self.client.patch(
            f"/api/concord/recordings/{recording.id}/",
            data={"title": "New", "summary": "Updated", "body": "New body"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recording.refresh_from_db()
        self.assertEqual(recording.title, "New")
        self.assertEqual(recording.summary, "Updated")
        self.assertEqual(recording.body, "New body")

    def test_delete_archives_recording(self):
        recording = self._create_recording()
        response = self.client.delete(f"/api/concord/recordings/{recording.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        recording.refresh_from_db()
        self.assertEqual(recording.status, RecordingStatus.ARCHIVED)

    def test_upload_rejects_non_audio(self):
        recording = self._create_recording()
        response = self.client.post(
            f"/api/concord/recordings/{recording.id}/upload/",
            data={"file": self._make_audio(name="test.txt", content_type="text/plain")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)

    def test_transition_valid_and_invalid(self):
        recording = self._create_recording()
        response = self.client.post(
            f"/api/concord/recordings/{recording.id}/transition/",
            data={"status": RecordingStatus.TRANSCRIBING},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recording.refresh_from_db()
        self.assertEqual(recording.status, RecordingStatus.TRANSCRIBING)
        self.assertIsNotNone(recording.processing_started_at)

        invalid_response = self.client.post(
            f"/api/concord/recordings/{recording.id}/transition/",
            data={"status": RecordingStatus.READY},
            format="json",
        )
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_group_endpoints(self):
        self._create_recording(title="Group Recording")

        list_response = self.client.get(f"/api/concord/groups/{self.group.slug}/recordings/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["group"]["slug"], self.group.slug)
        self.assertEqual(list_response.data["count"], 1)

        create_response = self.client.post(
            f"/api/concord/groups/{self.group.slug}/recordings/create/",
            data={"title": "Via Group"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["sponsor_type"], "group")
        self.assertEqual(create_response.data["sponsor_id"], str(self.group.id))

    def test_group_endpoints_missing_group(self):
        response = self.client.get("/api/concord/groups/missing/recordings/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(
            "/api/concord/groups/missing/recordings/create/",
            data={"title": "Test"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
