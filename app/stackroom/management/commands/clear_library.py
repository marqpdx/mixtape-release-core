"""
Django Management Command: clear_library

Clear all source files, artifacts, and related data from a library.
Also clears Qdrant vector collections for the library.
Useful for testing and development.

WARNING: This permanently deletes data. Use with caution.

Usage:
    python manage.py clear_library --library <uuid>
    python manage.py clear_library --library <uuid> --yes  # Skip confirmation
    python manage.py clear_library --all --yes  # Clear ALL libraries + orphaned Qdrant data

When using --all, this will also clean up orphaned Qdrant collections from deleted libraries.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Shard,
    Chunk,
    IngestionRun,
    ChunkEmbedding,
)
from stackroom.services.qdrant_client import get_qdrant_client


class Command(BaseCommand):
    help = "Clear all source files and artifacts from a library"

    def add_arguments(self, parser):
        parser.add_argument(
            "--library",
            type=str,
            help="Library UUID to clear",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Clear ALL libraries (use with extreme caution)",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        library_id = options.get("library")
        clear_all = options.get("all")
        skip_confirm = options.get("yes")

        # Validate arguments
        if not library_id and not clear_all:
            raise CommandError("Must specify either --library <uuid> or --all")

        if library_id and clear_all:
            raise CommandError("Cannot specify both --library and --all")

        # Get libraries to clear
        if clear_all:
            libraries = Library.objects.all()
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  WARNING: About to clear ALL {libraries.count()} libraries"
                )
            )
        else:
            try:
                libraries = [Library.objects.get(id=library_id)]
            except Library.DoesNotExist:
                raise CommandError(f"Library with ID {library_id} not found")

        # Show what will be deleted
        total_stats = {
            "source_files": 0,
            "ingestion_runs": 0,
            "artifacts": 0,
            "shards": 0,
            "chunks": 0,
            "embeddings": 0,
        }

        for library in libraries:
            source_files = SourceFile.objects.filter(library=library)
            source_file_ids = list(source_files.values_list("id", flat=True))

            chunks = Chunk.objects.filter(artifact__source_file_id__in=source_file_ids)
            chunk_ids = list(chunks.values_list("id", flat=True))

            stats = {
                "source_files": source_files.count(),
                "ingestion_runs": IngestionRun.objects.filter(
                    source_file_id__in=source_file_ids
                ).count(),
                "artifacts": Artifact.objects.filter(
                    source_file_id__in=source_file_ids
                ).count(),
                "shards": Shard.objects.filter(
                    artifact__source_file_id__in=source_file_ids
                ).count(),
                "chunks": chunks.count(),
                "embeddings": ChunkEmbedding.objects.filter(
                    chunk_id__in=chunk_ids
                ).count(),
            }

            self.stdout.write(f"\nLibrary: {library.name} ({library.id})")
            self.stdout.write(f"  Source Files: {stats['source_files']}")
            self.stdout.write(f"  Ingestion Runs: {stats['ingestion_runs']}")
            self.stdout.write(f"  Artifacts: {stats['artifacts']}")
            self.stdout.write(f"  Shards: {stats['shards']}")
            self.stdout.write(f"  Chunks: {stats['chunks']}")
            self.stdout.write(f"  Embeddings: {stats['embeddings']}")

            for key in total_stats:
                total_stats[key] += stats[key]

        # Confirmation
        if not skip_confirm:
            self.stdout.write(
                self.style.WARNING(
                    f"\n⚠️  This will permanently delete {total_stats['source_files']} source files "
                    f"and {total_stats['chunks']} chunks."
                )
            )
            confirm = input("Are you sure? Type 'yes' to confirm: ")
            if confirm.lower() != "yes":
                self.stdout.write(self.style.ERROR("Aborted."))
                return

        # Delete in correct order (children first to avoid FK constraints)
        with transaction.atomic():
            for library in libraries:
                source_files = SourceFile.objects.filter(library=library)
                source_file_ids = list(source_files.values_list("id", flat=True))

                # Get artifacts and chunks for these source files
                artifacts = Artifact.objects.filter(source_file_id__in=source_file_ids)
                artifact_ids = list(artifacts.values_list("id", flat=True))

                chunks = Chunk.objects.filter(artifact_id__in=artifact_ids)
                chunk_ids = list(chunks.values_list("id", flat=True))

                # Delete in order (children first to avoid FK constraints)
                # Note: ChunkEmbedding will cascade delete when Chunk is deleted
                embeddings_deleted = ChunkEmbedding.objects.filter(
                    chunk_id__in=chunk_ids
                ).delete()[0]
                chunks_deleted = chunks.delete()[0]
                shards_deleted = Shard.objects.filter(
                    artifact_id__in=artifact_ids
                ).delete()[0]
                artifacts_deleted = artifacts.delete()[0]
                ingestion_runs_deleted = IngestionRun.objects.filter(
                    source_file_id__in=source_file_ids
                ).delete()[0]
                source_files_deleted = source_files.delete()[0]

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✓ Cleared library: {library.name} ({library.id})"
                    )
                )
                self.stdout.write(f"  Deleted {source_files_deleted} source files")
                self.stdout.write(f"  Deleted {ingestion_runs_deleted} ingestion runs")
                self.stdout.write(f"  Deleted {artifacts_deleted} artifacts")
                self.stdout.write(f"  Deleted {shards_deleted} shards")
                self.stdout.write(f"  Deleted {chunks_deleted} chunks")
                self.stdout.write(f"  Deleted {embeddings_deleted} embeddings")

        # Clear Qdrant collections for these libraries
        self.stdout.write("\n🔍 Checking Qdrant collections...")
        try:
            qdrant = get_qdrant_client()
            all_collections = qdrant.client.get_collections().collections

            # When clearing all, also check for orphaned collections
            if clear_all:
                # Get all library IDs from database
                all_library_ids = set(str(lib.id) for lib in Library.objects.all())

                collections_deleted = 0
                for collection in all_collections:
                    # Only delete stackroom collections
                    if collection.name.startswith("stackroom__lib_"):
                        # Extract library ID from collection name
                        # Format: stackroom__lib_{uuid}__emb__...
                        parts = collection.name.split("__")
                        if len(parts) >= 3 and parts[1].startswith("lib_"):
                            collection_lib_id = parts[1][4:]  # Remove "lib_" prefix

                            # Delete if library no longer exists OR if clearing all
                            if collection_lib_id not in all_library_ids or clear_all:
                                is_orphaned = collection_lib_id not in all_library_ids
                                status = "orphaned" if is_orphaned else "active"
                                self.stdout.write(
                                    f"  Deleting {status} Qdrant collection: {collection.name}"
                                )
                                qdrant.client.delete_collection(collection.name)
                                collections_deleted += 1
            else:
                # Clearing specific library - only delete collections for that library
                collections_deleted = 0
                for library in libraries:
                    library_id_str = str(library.id)
                    for collection in all_collections:
                        if f"lib_{library_id_str}" in collection.name:
                            self.stdout.write(f"  Deleting Qdrant collection: {collection.name}")
                            qdrant.client.delete_collection(collection.name)
                            collections_deleted += 1

            if collections_deleted > 0:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Deleted {collections_deleted} Qdrant collections")
                )
            else:
                self.stdout.write("  No Qdrant collections found")

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"⚠️  Could not clear Qdrant collections: {e}")
            )
            self.stdout.write("  (Qdrant might not be running - database was cleared successfully)")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Successfully cleared {len(libraries)} "
                f"{'library' if len(libraries) == 1 else 'libraries'}"
            )
        )
