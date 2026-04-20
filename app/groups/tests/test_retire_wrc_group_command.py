from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from groups.models import Group
from writing.models import WorkingDocument, WritingPiece


User = get_user_model()


class RetireWrcGroupCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="testpass123",
        )
        self.deprecated_group = self._create_group(
            title="Old WRC",
            slug="wellness-resource-center",
        )
        self.surviving_group = self._create_group(
            title="Community Health Explorations",
            slug="community-health-explorations",
        )

    def _create_group(self, *, title, slug):
        group = Group(
            title=title,
            slug=slug,
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
        )
        group.set_sponsor(self.user)
        group.set_submitted_by(self.user)
        group.author = self.user
        group.author_name = self.user.username
        group.save()
        return group

    def _create_piece(self, *, sponsor_group, title, slug):
        piece = WritingPiece(
            title=title,
            slug=slug,
            body_json={"type": "doc", "content": []},
            excerpt="Excerpt",
            writing_kind="post",
            status="draft",
            author=self.user,
            author_name=self.user.username,
        )
        piece.set_sponsor(sponsor_group)
        piece.set_submitted_by(self.user)
        piece.save()
        return piece

    def test_reassigns_sponsor_content_and_deletes_deprecated_group(self):
        piece = self._create_piece(
            sponsor_group=self.deprecated_group,
            title="Migrated Piece",
            slug="migrated-piece",
        )

        call_command("retire_wrc_group")

        self.assertFalse(Group.objects.filter(id=self.deprecated_group.id).exists())

        surviving_group = Group.objects.get(id=self.surviving_group.id)
        self.assertEqual(surviving_group.slug, "wellness-resource-center")
        self.assertEqual(surviving_group.title, "Wellness Resource Center")

        piece.refresh_from_db()
        self.assertEqual(piece.sponsor_object_id, surviving_group.id)

    def test_dry_run_fails_fast_on_slug_collision(self):
        self._create_piece(
            sponsor_group=self.deprecated_group,
            title="Old Piece",
            slug="same-slug",
        )
        self._create_piece(
            sponsor_group=self.surviving_group,
            title="New Piece",
            slug="same-slug",
        )

        with self.assertRaises(CommandError):
            call_command("retire_wrc_group", "--dry-run", stdout=StringIO())

        self.assertTrue(Group.objects.filter(id=self.deprecated_group.id).exists())
        self.assertEqual(
            WritingPiece.objects.filter(
                sponsor_object_id=self.deprecated_group.id,
                slug="same-slug",
            ).count(),
            1,
        )

    def test_dry_run_lists_writing_piece_rows_and_working_copy_counts(self):
        piece = self._create_piece(
            sponsor_group=self.deprecated_group,
            title="Important Draft",
            slug="important-draft",
        )
        WorkingDocument.objects.create(
            piece=piece,
            user=self.user,
            body_json={"type": "doc", "content": []},
            title="Important Draft Working Copy",
            excerpt="Working excerpt",
        )

        stdout = StringIO()
        call_command("retire_wrc_group", "--dry-run", stdout=stdout)
        output = stdout.getvalue()

        self.assertIn("WritingPiece rows to reassign:", output)
        self.assertIn("slug=important-draft", output)
        self.assertIn("title='Important Draft'", output)
        self.assertIn("working_copies=1", output)
