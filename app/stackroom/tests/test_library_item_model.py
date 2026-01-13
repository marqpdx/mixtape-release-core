# stackroom/tests/test_library_item_model.py

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from groups.models.group import Group, GroupType
from stackroom.models import Library, LibraryItem, SourceFile


User = get_user_model()


def _create_group(*, sponsor_user: User, title: str, slug: str) -> Group:
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type=GroupType.COMMUNITY,
    )
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username
    group.save()
    return group


def _create_library(*, sponsor, submitted_by: User, title: str) -> Library:
    library = Library(title=title)
    library.set_sponsor(sponsor)
    library.set_submitted_by(submitted_by)
    library.author = submitted_by
    library.author_name = submitted_by.get_full_name() or submitted_by.username
    library.save()
    return library


class LibraryItemModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.group = _create_group(
            sponsor_user=self.user,
            title="Test Group",
            slug="test-group-model",
        )
        self.library = _create_library(
            sponsor=self.group,
            submitted_by=self.user,
            title="Test Library",
        )
        self.source_file = SourceFile.objects.create(
            library=self.library,
            origin="upload",
            path="docs/test.txt",
            filename="test.txt",
            content_type="text/plain",
            size_bytes=10,
            hash_sha256="abc123" * 10,
            created_by=self.user,
        )

    def test_unique_source_file_position(self):
        LibraryItem.objects.create(
            library=self.library,
            content_object=self.source_file,
            order_index=1,
        )
        with transaction.atomic():
            with self.assertRaises(ValidationError):
                LibraryItem.objects.create(
                    library=self.library,
                    content_object=self.source_file,
                    order_index=1,
                )

    def test_same_source_file_different_positions_allowed(self):
        LibraryItem.objects.create(
            library=self.library,
            content_object=self.source_file,
            order_index=1,
        )
        LibraryItem.objects.create(
            library=self.library,
            content_object=self.source_file,
            order_index=2,
        )
        count = LibraryItem.objects.filter(
            library=self.library,
            content_object_id=self.source_file.id,
        ).count()
        self.assertEqual(count, 2)

    def test_defaults(self):
        item = LibraryItem.objects.create(
            library=self.library,
            content_object=self.source_file,
            order_index=1,
        )
        self.assertEqual(item.folder_path, "")
        self.assertEqual(item.tags, [])
        self.assertEqual(item.notes, "")
        self.assertFalse(item.is_featured)
        self.assertFalse(item.is_hidden)
