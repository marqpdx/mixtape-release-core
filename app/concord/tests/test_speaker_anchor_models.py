# concord/tests/test_speaker_anchor_models.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase

from concord.models import RecordingSession, SessionStatus, SpeakerAnchor
from groups.models import Group


User = get_user_model()


class SpeakerAnchorModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="anchor-user",
            email="anchor@example.com",
            password="testpass123",
        )
        self.group = Group.objects.create(
            title="Anchor Group",
            slug="anchor-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        self.group_ct = ContentType.objects.get_for_model(Group)
        self.session = RecordingSession.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            title="Anchor Session",
            submitted_by=self.user,
            status=SessionStatus.RECORDING,
        )

    def test_anchor_requires_scope(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SpeakerAnchor.objects.create(
                    speaker_label="No Scope",
                    user=self.user,
                )

    def test_anchor_allows_group_scope(self):
        anchor = SpeakerAnchor.objects.create(
            group=self.group,
            speaker_label="Group Speaker",
            user=self.user,
        )
        self.assertEqual(anchor.group_id, self.group.id)
        self.assertIsNone(anchor.session)

    def test_anchor_allows_session_scope(self):
        anchor = SpeakerAnchor.objects.create(
            session=self.session,
            speaker_label="Session Speaker",
            user=self.user,
        )
        self.assertEqual(anchor.session_id, self.session.id)
        self.assertIsNone(anchor.group)

    def test_anchor_allows_both_scopes(self):
        anchor = SpeakerAnchor.objects.create(
            session=self.session,
            group=self.group,
            speaker_label="Dual Speaker",
            user=self.user,
        )
        self.assertEqual(anchor.session_id, self.session.id)
        self.assertEqual(anchor.group_id, self.group.id)
