# publishing/tests/test_content_access.py

"""
Tests for content_access service.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from publishing.models import ContentPlacement, PublicationGroup
from publishing.services.content_access import (
    can_view_placement,
    can_place_content,
)
from writing.models import WritingPiece, WritingVersion

User = get_user_model()


class ContentAccessServiceTest(TestCase):
    """Test content access service functions."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
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

        # Create a version
        self.version = WritingVersion.objects.create(
            writing_piece=self.piece,
            sequence_no=1,
            version_label="1",
            body_json={'type': 'doc', 'content': []},
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

    def test_can_view_public_placement(self):
        """Test that anyone can view public placements."""
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

        # Anonymous user can view
        self.assertTrue(can_view_placement(placement, None))

        # Authenticated users can view
        self.assertTrue(can_view_placement(placement, self.user))
        self.assertTrue(can_view_placement(placement, self.other_user))

    def test_can_view_private_placement(self):
        """Test that only authorized users can view private placements."""
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
            visibility='private',
            follow_updates=True,
        )

        # Anonymous user cannot view
        self.assertFalse(can_view_placement(placement, None))

        # Author can view
        self.assertTrue(can_view_placement(placement, self.user))

        # Other users cannot view
        self.assertFalse(can_view_placement(placement, self.other_user))

    def test_can_view_members_placement(self):
        """Test members-only placement visibility."""
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        ct_user = ContentType.objects.get_for_model(User)

        # Placement to user's own profile
        placement = ContentPlacement.objects.create(
            publication_group=self.pub_group,
            placed_by=self.user,
            source_content_type=ct_piece,
            source_object_id=self.piece.id,
            target_content_type=ct_user,
            target_object_id=self.user.id,
            channel='feed',
            visibility='members',
            follow_updates=True,
        )

        # Anonymous user cannot view
        self.assertFalse(can_view_placement(placement, None))

        # Target user can view their own profile
        self.assertTrue(can_view_placement(placement, self.user))

        # Other users cannot view (not a member of target user)
        self.assertFalse(can_view_placement(placement, self.other_user))

    def test_can_place_content(self):
        """Test that only authors can place their content."""
        # Author can place their own content
        self.assertTrue(can_place_content(self.piece, self.user, self.user))

        # Other users cannot place someone else's content
        self.assertFalse(can_place_content(self.piece, self.user, self.other_user))

        # Anonymous users cannot place content
        self.assertFalse(can_place_content(self.piece, self.user, None))
