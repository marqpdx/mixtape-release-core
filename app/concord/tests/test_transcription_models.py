# concord/tests/test_transcription_models.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase

from concord.models import Recording, RecordingStatus, Transcription, TranscriptSegment
from groups.models import Group


User = get_user_model()


class TranscriptionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="transcription-user",
            email="transcription@example.com",
            password="testpass123",
        )
        self.group = self._create_group(
            sponsor_user=self.user,
            title="Transcription Group",
            slug="transcription-group",
        )
        self.group_ct = ContentType.objects.get_for_model(Group)
        self.recording = Recording.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            title="Transcription Recording",
            submitted_by=self.user,
            status=RecordingStatus.UPLOADED,
        )

    def _create_group(self, *, sponsor_user, title, slug):
        group = Group(
            title=title,
            slug=slug,
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        group.set_sponsor(sponsor_user)
        group.set_submitted_by(sponsor_user)
        group.author = sponsor_user
        group.author_name = sponsor_user.get_full_name() or sponsor_user.username
        group.save()
        return group

    def test_unique_version_per_recording(self):
        Transcription.objects.create(recording=self.recording, version=1, text="v1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Transcription.objects.create(recording=self.recording, version=1, text="dup")

    def test_transcription_cascade_delete(self):
        transcription = Transcription.objects.create(recording=self.recording, version=1, text="v1")
        self.recording.delete()
        self.assertFalse(Transcription.objects.filter(id=transcription.id).exists())


class TranscriptSegmentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="segment-user",
            email="segment@example.com",
            password="testpass123",
        )
        self.group = self._create_group(
            sponsor_user=self.user,
            title="Segment Group",
            slug="segment-group",
        )
        group_ct = ContentType.objects.get_for_model(Group)
        recording = Recording.objects.create(
            sponsor_content_type=group_ct,
            sponsor_object_id=self.group.id,
            title="Segment Recording",
            submitted_by=self.user,
            status=RecordingStatus.UPLOADED,
        )
        self.transcription = Transcription.objects.create(recording=recording, version=1, text="v1")

    def _create_group(self, *, sponsor_user, title, slug):
        group = Group(
            title=title,
            slug=slug,
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        group.set_sponsor(sponsor_user)
        group.set_submitted_by(sponsor_user)
        group.author = sponsor_user
        group.author_name = sponsor_user.get_full_name() or sponsor_user.username
        group.save()
        return group

    def test_segment_duration_and_ordering(self):
        TranscriptSegment.objects.create(
            transcription=self.transcription,
            segment_index=2,
            start_ms=10000,
            end_ms=15000,
            text="Third",
        )
        TranscriptSegment.objects.create(
            transcription=self.transcription,
            segment_index=0,
            start_ms=0,
            end_ms=4000,
            text="First",
        )
        TranscriptSegment.objects.create(
            transcription=self.transcription,
            segment_index=1,
            start_ms=4000,
            end_ms=9000,
            text="Second",
        )

        segments = list(self.transcription.segments.all())
        self.assertEqual([seg.segment_index for seg in segments], [0, 1, 2])
        self.assertEqual(segments[0].duration_ms, 4000)
