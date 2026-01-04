"""
Management command to archive (delete) old Qdrant collections.

Usage:
    # List all collections
    python manage.py archive_collections --list

    # Archive a specific collection (with confirmation)
    python manage.py archive_collections --collection library-abc123-model-text-embedding-3-small-v1

    # Archive collections matching pattern
    python manage.py archive_collections --pattern "library-oldlib-*"

    # Dry run (show what would be deleted)
    python manage.py archive_collections --pattern "library-*" --dry-run

    # Archive all collections for a specific library
    python manage.py archive_collections --library-id abc-123-def

    # Skip confirmation prompt (use with caution!)
    python manage.py archive_collections --collection my-collection --force
"""

from django.core.management.base import BaseCommand, CommandError
from stackroom.services.qdrant_client import get_qdrant_client
from stackroom.models import Library
import fnmatch


class Command(BaseCommand):
    help = "Archive (delete) old Qdrant collections"

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all collections",
        )

        parser.add_argument(
            "--collection",
            type=str,
            help="Archive a specific collection by name",
        )

        parser.add_argument(
            "--pattern",
            type=str,
            help="Archive collections matching glob pattern (e.g., 'library-oldlib-*')",
        )

        parser.add_argument(
            "--library-id",
            type=str,
            help="Archive all collections for a specific library ID",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompts (use with caution!)",
        )

    def handle(self, *args, **options):
        try:
            qdrant_client = get_qdrant_client()
        except Exception as e:
            raise CommandError(f"Failed to connect to Qdrant: {e}")

        # List collections
        if options["list"]:
            self._list_collections(qdrant_client)
            return

        # Determine which collections to archive
        collections_to_archive = self._get_collections_to_archive(
            qdrant_client, options
        )

        if not collections_to_archive:
            self.stdout.write(self.style.WARNING("No collections found to archive"))
            return

        # Show what will be archived
        self.stdout.write(
            self.style.WARNING(
                f"\nThe following {len(collections_to_archive)} collection(s) will be archived:"
            )
        )
        for collection_name in collections_to_archive:
            self.stdout.write(f"  - {collection_name}")

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n[DRY RUN] No collections were deleted. Use without --dry-run to actually archive."
                )
            )
            return

        # Confirm unless --force
        if not options["force"]:
            confirm = input(
                "\nAre you sure you want to delete these collections? [y/N]: "
            )
            if confirm.lower() != "y":
                self.stdout.write(self.style.WARNING("Archival cancelled"))
                return

        # Archive collections
        self._archive_collections(qdrant_client, collections_to_archive)

    def _list_collections(self, qdrant_client):
        """List all Qdrant collections"""
        try:
            collections = qdrant_client.list_collections()

            if not collections:
                self.stdout.write(self.style.WARNING("No collections found"))
                return

            self.stdout.write(
                self.style.SUCCESS(f"\nFound {len(collections)} collection(s):")
            )
            for collection_name in sorted(collections):
                self.stdout.write(f"  - {collection_name}")

        except Exception as e:
            raise CommandError(f"Failed to list collections: {e}")

    def _get_collections_to_archive(self, qdrant_client, options):
        """Determine which collections to archive based on options"""
        try:
            all_collections = qdrant_client.list_collections()
        except Exception as e:
            raise CommandError(f"Failed to list collections: {e}")

        # Single collection
        if options["collection"]:
            collection_name = options["collection"]
            if collection_name in all_collections:
                return [collection_name]
            else:
                raise CommandError(f"Collection '{collection_name}' not found")

        # Pattern matching
        if options["pattern"]:
            pattern = options["pattern"]
            matching = [
                c for c in all_collections if fnmatch.fnmatch(c, pattern)
            ]
            return matching

        # Library ID
        if options["library_id"]:
            library_id = options["library_id"]

            # Verify library exists
            try:
                library = Library.objects.get(id=library_id)
            except Library.DoesNotExist:
                raise CommandError(f"Library '{library_id}' not found")

            # Find collections for this library
            # Collection naming pattern: library-{id}-model-{name}-{version}
            prefix = f"library-{library_id}-"
            matching = [
                c for c in all_collections if c.startswith(prefix)
            ]
            return matching

        # No filter specified
        raise CommandError(
            "You must specify one of: --list, --collection, --pattern, or --library-id"
        )

    def _archive_collections(self, qdrant_client, collections):
        """Delete collections from Qdrant"""
        success_count = 0
        error_count = 0

        for collection_name in collections:
            try:
                qdrant_client.delete_collection(collection_name)
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Archived: {collection_name}")
                )
                success_count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ Failed to archive {collection_name}: {e}")
                )
                error_count += 1

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nArchival complete: {success_count} succeeded, {error_count} failed"
            )
        )
