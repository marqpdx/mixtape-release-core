# publishing/tests/test_content_placement_constraints.py

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from publishing.models import ContentPlacement, PublicationGroup
from writing.models import WritingPiece, WritingVersion


User = get_user_model()


class ContentPlacementConstraintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="constraintuser",
            email="constraint@example.com",
            password="testpass123",
        )
        ct_user = ContentType.objects.get_for_model(User)
        self.piece = WritingPiece.objects.create(
            author=self.user,
            title="Constraint Test",
            excerpt="Constraint excerpt",
            body_json={"type": "doc", "content": []},
            status="published",
            published_at=timezone.now(),
            sponsor_content_type=ct_user,
            sponsor_object_id=self.user.id,
        )
        self.version = WritingVersion.objects.create(
            writing_piece=self.piece,
            sequence_no=1,
            version_label="1",
            body_json={"type": "doc", "content": []},
            title="Constraint Test",
            excerpt="Constraint excerpt",
            kind="release",
            created_by=self.user,
        )
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        self.pub_group = PublicationGroup.objects.create(
            created_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
        )
        self.ct_piece = ct_piece
        self.ct_user = ct_user
        self.ct_version = ContentType.objects.get_for_model(WritingVersion)

    def test_invalid_unlocked_without_follow_updates(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            ContentPlacement.objects.create(
                publication_group=self.pub_group,
                placed_by=self.user,
                source_content_type=self.ct_piece,
                source_object_id=self.piece.id,
                target_content_type=self.ct_user,
                target_object_id=self.user.id,
                channel="feed",
                visibility="public",
                follow_updates=False,
            )

    def test_invalid_follow_updates_with_lock(self):
        with self.assertRaises((ValidationError, IntegrityError)):
            ContentPlacement.objects.create(
                publication_group=self.pub_group,
                placed_by=self.user,
                source_content_type=self.ct_piece,
                source_object_id=self.piece.id,
                target_content_type=self.ct_user,
                target_object_id=self.user.id,
                channel="feed",
                visibility="public",
                follow_updates=True,
                locked_artifact_content_type=self.ct_version,
                locked_artifact_object_id=self.version.id,
            )

    def test_valid_follow_updates_without_lock(self):
        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=self.ct_piece,
            source_object_id=self.piece.id,
            target_content_type=self.ct_user,
            target_object_id=self.user.id,
            channel="feed",
            visibility="public",
            follow_updates=True,
        )
        self.assertTrue(placement.follow_updates)
        self.assertIsNone(placement.locked_artifact_content_type)
        self.assertIsNone(placement.locked_artifact_object_id)

    def test_valid_locked_without_follow_updates(self):
        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=self.ct_piece,
            source_object_id=self.piece.id,
            target_content_type=self.ct_user,
            target_object_id=self.user.id,
            channel="feed",
            visibility="public",
            follow_updates=False,
            locked_artifact_content_type=self.ct_version,
            locked_artifact_object_id=self.version.id,
        )
        self.assertFalse(placement.follow_updates)
        self.assertEqual(placement.locked_artifact_content_type, self.ct_version)
        self.assertEqual(placement.locked_artifact_object_id, self.version.id)
