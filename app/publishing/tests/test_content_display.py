# publishing/tests/test_content_display.py

"""
Tests for content_display service.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from publishing.models import ContentPlacement, PublicationGroup
from publishing.services.content_display import (
    get_display_payload,
    resolve_artifact_for_source,
)
from writing.models import WritingPiece, WritingVersion

User = get_user_model()


class ContentDisplayServiceTest(TestCase):
    """Test content display service functions."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create a writing piece with sponsor
        from django.utils import timezone
        ct_user = ContentType.objects.get_for_model(User)
        self.piece = WritingPiece.objects.create(
            author=self.user,
            title='Test Article',
            excerpt='Test excerpt',
            body_json={'type': 'doc', 'content': []},
            status='published',
            published_at=timezone.now(),
            writing_kind='article',
            sponsor_content_type=ct_user,
            sponsor_object_id=self.user.id,
        )

        # Create a version (artifact)
        self.version = WritingVersion.objects.create(
            writing_piece=self.piece,
            sequence_no=1,
            version_label="1",
            body_json={'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Test content'}]}]},
            title='Test Article',
            excerpt='Test excerpt',
            kind='release',
            created_by=self.user,
        )

        # Create publication group
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        self.pub_group = PublicationGroup.objects.create(
            created_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
        )

    def test_get_display_payload_with_locked_artifact(self):
        """Test getting display payload with locked artifact."""
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        ct_user = ContentType.objects.get_for_model(User)
        ct_version = ContentType.objects.get_for_model(WritingVersion)

        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
            target_content_type=ct_user,
            target_object_id=self.user.id,
            channel='feed',
            visibility='public',
            follow_updates=False,
            locked_artifact_content_type=ct_version,
            locked_artifact_object_id=self.version.id,
        )

        payload = get_display_payload(placement)

        self.assertEqual(payload['artifact'], self.version)
        self.assertEqual(payload['source'], self.piece)
        self.assertEqual(payload['metadata']['title'], 'Test Article')
        self.assertEqual(payload['metadata']['channel'], 'feed')

    def test_get_display_payload_with_follow_updates(self):
        """Test getting display payload with follow_updates=True."""
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        ct_user = ContentType.objects.get_for_model(User)

        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
            target_content_type=ct_user,
            target_object_id=self.user.id,
            channel='feed',
            visibility='public',
            follow_updates=True,
        )

        payload = get_display_payload(placement)

        self.assertEqual(payload['artifact'], self.version)
        self.assertEqual(payload['source'], self.piece)

    def test_get_display_payload_with_overrides(self):
        """Test that placement overrides are applied to metadata."""
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        ct_user = ContentType.objects.get_for_model(User)

        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
            target_content_type=ct_user,
            target_object_id=self.user.id,
            channel='feed',
            visibility='public',
            follow_updates=True,
            overrides={
                'title': 'Override Title',
                'excerpt': 'Override excerpt',
            }
        )

        payload = get_display_payload(placement)

        self.assertEqual(payload['metadata']['title'], 'Override Title')
        self.assertEqual(payload['metadata']['excerpt'], 'Override excerpt')

    def test_resolve_artifact_for_source(self):
        """Test resolving artifact for a source."""
        # Get current artifact
        artifact = resolve_artifact_for_source(self.piece)
        self.assertEqual(artifact, self.version)

        # Get locked artifact by ID
        artifact = resolve_artifact_for_source(self.piece, self.version.id)
        self.assertEqual(artifact, self.version)
