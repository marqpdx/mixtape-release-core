# concord/tests/test_session_models.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from concord.models import Recording, RecordingSession, RecordingStatus, SessionStatus
from groups.models import Group


User = get_user_model()


class RecordingSessionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="session-user",
            email="session@example.com",
            password="testpass123",
        )
        self.group = Group.objects.create(
            title="Session Group",
            slug="session-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        self.group_ct = ContentType.objects.get_for_model(Group)

    def _create_session(self, **kwargs):
        return RecordingSession.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            title=kwargs.get("title", "Test Session"),
            submitted_by=self.user,
            status=kwargs.get("status", SessionStatus.RECORDING),
            expected_participants=kwargs.get("expected_participants", []),
            segment_duration_seconds=kwargs.get("segment_duration_seconds", 900),
        )

    def test_session_defaults(self):
        session = self._create_session()
        self.assertEqual(session.status, SessionStatus.RECORDING)
        self.assertEqual(session.segment_duration_seconds, 900)
        self.assertEqual(session.expected_participants, [])

    def test_session_segment_helpers(self):
        session = self._create_session()
        Recording.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            session=session,
            segment_index=0,
            duration_ms=60000,
            submitted_by=self.user,
            status=RecordingStatus.UPLOADED,
        )
        Recording.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            session=session,
            segment_index=1,
            duration_ms=90000,
            submitted_by=self.user,
            status=RecordingStatus.UPLOADED,
        )

        self.assertEqual(session.segment_count, 2)
        self.assertEqual(session.total_duration_ms, 150000)
