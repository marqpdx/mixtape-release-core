# concord/tests/test_recording_models.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils.text import slugify

from concord.models import Recording, RecordingStatus
from groups.models import Group


User = get_user_model()


class RecordingModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="recording-user",
            email="recording@example.com",
            password="testpass123",
        )
        self.group = Group.objects.create(
            title="Recording Group",
            slug="recording-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        self.group_ct = ContentType.objects.get_for_model(Group)

    def _create_recording(self, **kwargs):
        return Recording.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            title=kwargs.get("title", "Test Recording"),
            submitted_by=self.user,
            status=kwargs.get("status", RecordingStatus.UPLOADED),
            duration_ms=kwargs.get("duration_ms"),
        )

    def test_duration_helpers(self):
        recording = self._create_recording(duration_ms=123456)
        self.assertAlmostEqual(recording.duration_seconds, 123.456)
        self.assertEqual(recording.duration_formatted, "2:03")

    def test_status_transitions_and_timestamps(self):
        recording = self._create_recording()
        old_changed_at = recording.status_changed_at

        recording.transition_to(RecordingStatus.TRANSCRIBING)
        recording.refresh_from_db()
        self.assertEqual(recording.status, RecordingStatus.TRANSCRIBING)
        self.assertNotEqual(recording.status_changed_at, old_changed_at)
        self.assertIsNotNone(recording.processing_started_at)
        self.assertIsNone(recording.processing_completed_at)

        recording.transition_to(RecordingStatus.INTERPRETING)
        recording.refresh_from_db()
        self.assertEqual(recording.status, RecordingStatus.INTERPRETING)

        recording.transition_to(RecordingStatus.READY)
        recording.refresh_from_db()
        self.assertEqual(recording.status, RecordingStatus.READY)
        self.assertIsNotNone(recording.processing_completed_at)

        with self.assertRaises(ValueError):
            recording.transition_to(RecordingStatus.TRANSCRIBING)

    def test_slug_uniqueness_per_sponsor(self):
        title = "My Recording"
        first = self._create_recording(title=title)
        second = self._create_recording(title=title)

        self.assertNotEqual(first.slug, second.slug)
        self.assertTrue(first.slug.startswith(slugify(title)))
        self.assertTrue(second.slug.startswith(slugify(title)))

        other_group = Group.objects.create(
            title="Other Group",
            slug="other-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        other_recording = Recording.objects.create(
            sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=other_group.id,
            title=title,
            submitted_by=self.user,
            status=RecordingStatus.UPLOADED,
        )
        self.assertEqual(other_recording.slug, first.slug)
