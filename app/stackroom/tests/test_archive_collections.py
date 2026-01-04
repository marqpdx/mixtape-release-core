"""
Tests for archive_collections management command

Tests the collection archival functionality:
- List all collections
- Archive specific collection
- Archive by pattern
- Archive by library ID
- Dry run mode
- Force mode
"""

from unittest.mock import patch, Mock
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.contrib.auth import get_user_model

from stackroom.models import Library


class ArchiveCollectionsTests(TestCase):
    """Test archive_collections management command"""

    def setUp(self):
        """Set up test fixtures"""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )

        # Create test library
        self.library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant",
            name="Test Library",
        )

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_list_collections(self, mock_get_qdrant):
        """Test --list flag shows all collections"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
            "library-xyz-model-text-embedding-3-large-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command
        call_command("archive_collections", "--list", stdout=out)

        # Verify output
        output = out.getvalue()
        self.assertIn("Found 2 collection(s)", output)
        self.assertIn("library-abc-model-text-embedding-3-small-v1", output)
        self.assertIn("library-xyz-model-text-embedding-3-large-v1", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_list_no_collections(self, mock_get_qdrant):
        """Test --list when no collections exist"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command
        call_command("archive_collections", "--list", stdout=out)

        # Verify output
        output = out.getvalue()
        self.assertIn("No collections found", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="y")
    def test_archive_specific_collection(self, mock_input, mock_get_qdrant):
        """Test archiving a specific collection"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
            "library-xyz-model-text-embedding-3-large-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command
        call_command(
            "archive_collections",
            "--collection", "library-abc-model-text-embedding-3-small-v1",
            stdout=out
        )

        # Verify delete was called
        mock_qdrant.delete_collection.assert_called_once_with(
            "library-abc-model-text-embedding-3-small-v1"
        )

        # Verify output
        output = out.getvalue()
        self.assertIn("✓ Archived: library-abc-model-text-embedding-3-small-v1", output)
        self.assertIn("1 succeeded, 0 failed", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_archive_nonexistent_collection(self, mock_get_qdrant):
        """Test archiving a collection that doesn't exist"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Call command - should raise error
        with self.assertRaises(CommandError) as cm:
            call_command(
                "archive_collections",
                "--collection", "nonexistent-collection",
                stdout=StringIO()
            )

        self.assertIn("not found", str(cm.exception))

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="y")
    def test_archive_by_pattern(self, mock_input, mock_get_qdrant):
        """Test archiving collections matching pattern"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
            "library-abc-model-text-embedding-3-large-v1",
            "library-xyz-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command - pattern matches first two
        call_command(
            "archive_collections",
            "--pattern", "library-abc-*",
            stdout=out
        )

        # Verify deletes were called for matching collections
        self.assertEqual(mock_qdrant.delete_collection.call_count, 2)
        mock_qdrant.delete_collection.assert_any_call(
            "library-abc-model-text-embedding-3-small-v1"
        )
        mock_qdrant.delete_collection.assert_any_call(
            "library-abc-model-text-embedding-3-large-v1"
        )

        # Verify output
        output = out.getvalue()
        self.assertIn("2 collection(s) will be archived", output)
        self.assertIn("2 succeeded, 0 failed", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="y")
    def test_archive_by_library_id(self, mock_input, mock_get_qdrant):
        """Test archiving all collections for a library"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            f"library-{self.library.id}-model-text-embedding-3-small-v1",
            f"library-{self.library.id}-model-text-embedding-3-large-v1",
            "library-other-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command
        call_command(
            "archive_collections",
            "--library-id", str(self.library.id),
            stdout=out
        )

        # Verify deletes were called for library collections only
        self.assertEqual(mock_qdrant.delete_collection.call_count, 2)

        # Verify output
        output = out.getvalue()
        self.assertIn("2 collection(s) will be archived", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_archive_by_invalid_library_id(self, mock_get_qdrant):
        """Test archiving with non-existent library ID"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Call command - should raise error
        with self.assertRaises(CommandError) as cm:
            call_command(
                "archive_collections",
                "--library-id", "00000000-0000-0000-0000-000000000000",
                stdout=StringIO()
            )

        self.assertIn("not found", str(cm.exception))

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_dry_run_mode(self, mock_get_qdrant):
        """Test --dry-run doesn't actually delete"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command with dry-run
        call_command(
            "archive_collections",
            "--collection", "library-abc-model-text-embedding-3-small-v1",
            "--dry-run",
            stdout=out
        )

        # Verify delete was NOT called
        mock_qdrant.delete_collection.assert_not_called()

        # Verify output indicates dry run
        output = out.getvalue()
        self.assertIn("[DRY RUN]", output)
        self.assertIn("No collections were deleted", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="n")
    def test_confirmation_cancelled(self, mock_input, mock_get_qdrant):
        """Test user can cancel archival at confirmation prompt"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command - user will say no
        call_command(
            "archive_collections",
            "--collection", "library-abc-model-text-embedding-3-small-v1",
            stdout=out
        )

        # Verify delete was NOT called
        mock_qdrant.delete_collection.assert_not_called()

        # Verify output
        output = out.getvalue()
        self.assertIn("Archival cancelled", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_force_mode_skips_confirmation(self, mock_get_qdrant):
        """Test --force skips confirmation prompt"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command with --force (no input mock needed)
        call_command(
            "archive_collections",
            "--collection", "library-abc-model-text-embedding-3-small-v1",
            "--force",
            stdout=out
        )

        # Verify delete was called (without confirmation)
        mock_qdrant.delete_collection.assert_called_once()

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="y")
    def test_error_during_deletion(self, mock_input, mock_get_qdrant):
        """Test handling of errors during deletion"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        # Make delete raise an error
        mock_qdrant.delete_collection.side_effect = Exception("Delete failed")
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command - should handle error gracefully
        call_command(
            "archive_collections",
            "--collection", "library-abc-model-text-embedding-3-small-v1",
            stdout=out
        )

        # Verify output shows error
        output = out.getvalue()
        self.assertIn("✗ Failed to archive", output)
        self.assertIn("Delete failed", output)
        self.assertIn("0 succeeded, 1 failed", output)

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    def test_no_filters_specified(self, mock_get_qdrant):
        """Test error when no filters specified"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_qdrant.return_value = mock_qdrant

        # Call command without any filters - should raise error
        with self.assertRaises(CommandError) as cm:
            call_command("archive_collections", stdout=StringIO())

        self.assertIn("You must specify one of", str(cm.exception))

    @patch("stackroom.management.commands.archive_collections.get_qdrant_client")
    @patch("builtins.input", return_value="y")
    def test_pattern_no_matches(self, mock_input, mock_get_qdrant):
        """Test pattern that matches no collections"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = [
            "library-abc-model-text-embedding-3-small-v1",
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Capture output
        out = StringIO()

        # Call command with pattern that doesn't match
        call_command(
            "archive_collections",
            "--pattern", "library-xyz-*",
            stdout=out
        )

        # Verify no deletes
        mock_qdrant.delete_collection.assert_not_called()

        # Verify output
        output = out.getvalue()
        self.assertIn("No collections found to archive", output)
