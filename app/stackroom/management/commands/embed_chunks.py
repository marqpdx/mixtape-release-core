"""
Django Management Command: embed_chunks

Manually trigger embedding generation for library chunks.

Usage:
    python manage.py embed_chunks --library <id> --model <name> --version <version>
    python manage.py embed_chunks --library <id> --sync  # Synchronous mode
    python manage.py embed_chunks --stats  # Show statistics
    python manage.py embed_chunks --mark-stale  # Mark stale embeddings
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stackroom.models import Library, EmbeddingModel, EmbeddingStatus
from stackroom.services.embeddings import (
    get_or_create_embedding_model,
    backfill_library_embeddings,
    get_pending_embeddings,
    get_embedding_stats,
    get_stale_embeddings,
    mark_stale_embeddings_pending,
)
from stackroom.services.embedding_provider import embed_texts
from stackroom.services.qdrant_client import (
    get_qdrant_client,
    build_payload_from_embedding,
)
from stackroom.tasks.embeddings import embed_library, embed_chunk_embedding


class Command(BaseCommand):
    help = "Embed library chunks using specified embedding model"

    def add_arguments(self, parser):
        # Library selection
        parser.add_argument(
            "--library",
            type=str,
            help="Library UUID to embed",
        )

        # Model selection
        parser.add_argument(
            "--model",
            type=str,
            default="text-embedding-3-small",
            help="Embedding model name (default: text-embedding-3-small)",
        )

        parser.add_argument(
            "--model-version",
            type=str,
            default="1",
            help="Embedding model version (default: 1)",
        )

        parser.add_argument(
            "--provider",
            type=str,
            default="openai",
            choices=["openai", "sentence-transformers", "local"],
            help="Embedding provider (default: openai)",
        )

        # Execution modes
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously (for testing, blocks until complete)",
        )

        parser.add_argument(
            "--async",
            dest="async_mode",
            action="store_true",
            help="Run asynchronously via Celery (default)",
        )

        # Actions
        parser.add_argument(
            "--stats",
            action="store_true",
            help="Show embedding statistics",
        )

        parser.add_argument(
            "--mark-stale",
            action="store_true",
            help="Mark stale embeddings as PENDING",
        )

        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of chunks to process (sync mode only)",
        )

    def handle(self, *args, **options):
        # Show stats mode
        if options["stats"]:
            self.show_stats(options)
            return

        # Mark stale mode
        if options["mark_stale"]:
            self.mark_stale(options)
            return

        # Validate library required for embedding
        if not options["library"]:
            raise CommandError("--library is required for embedding operations")

        # Get library
        try:
            library = Library.objects.get(id=options["library"])
        except Library.DoesNotExist:
            raise CommandError(f"Library {options['library']} not found")

        self.stdout.write(f"Library: {library.name}")
        self.stdout.write(f"Model: {options['model']}@{options['model_version']}")
        self.stdout.write(f"Provider: {options['provider']}")

        # Determine execution mode
        if options["sync"]:
            self.embed_sync(library, options)
        else:
            self.embed_async(library, options)

    def embed_async(self, library, options):
        """Embed using Celery tasks (default)"""
        self.stdout.write(self.style.SUCCESS("\n🚀 Starting async embedding..."))

        # Trigger embed_library task
        result = embed_library.delay(
            library_id=str(library.id),
            model_name=options["model"],
            model_version=options["model_version"],
            provider=options["provider"],
        )

        self.stdout.write(
            self.style.SUCCESS(f"✅ Task enqueued: {result.id}")
        )
        self.stdout.write(
            "Monitor progress with: celery -A mixtape inspect active"
        )

    def embed_sync(self, library, options):
        """Embed synchronously (for testing/debugging)"""
        self.stdout.write(self.style.WARNING("\n⚠️  Running in SYNC mode..."))

        # Get or create embedding model
        embedding_model, created = get_or_create_embedding_model(
            name=options["model"],
            version=options["model_version"],
            provider=options["provider"],
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"✅ Created EmbeddingModel: {embedding_model}")
            )

        # Backfill
        self.stdout.write("📊 Backfilling ChunkEmbedding rows...")
        stats = backfill_library_embeddings(
            library_id=library.id,
            model_name=options["model"],
            model_version=options["model_version"],
            provider=options["provider"],
        )

        self.stdout.write(
            f"   Created: {stats['created']}, Existing: {stats['existing']}"
        )
        self.stdout.write(f"   Collection: {stats['collection']}")

        # Get pending
        limit = options.get("limit")
        pending = get_pending_embeddings(
            library=library,
            embedding_model=embedding_model,
            limit=limit,
        )

        total = len(pending)
        self.stdout.write(f"\n🔄 Processing {total} chunks synchronously...")

        # Process each chunk
        qdrant_client = get_qdrant_client()
        success_count = 0
        error_count = 0

        for i, chunk_embedding in enumerate(pending, 1):
            try:
                # Get text
                text = chunk_embedding.chunk.text

                # Embed
                vectors = embed_texts(
                    texts=[text],
                    embedding_model=embedding_model,
                )

                if not vectors:
                    raise ValueError("No vector returned")

                # Upsert to Qdrant
                payload = build_payload_from_embedding(chunk_embedding)
                qdrant_client.upsert_point(
                    collection_name=chunk_embedding.qdrant_collection,
                    point_id=chunk_embedding.qdrant_point_id,
                    vector=vectors[0],
                    payload=payload,
                )

                # Mark complete
                chunk_embedding.mark_complete()
                chunk_embedding.save()

                success_count += 1
                self.stdout.write(
                    f"  [{i}/{total}] ✓ {chunk_embedding.chunk_id}",
                    ending="\r",
                )

            except Exception as e:
                error_count += 1
                chunk_embedding.mark_failed(
                    code=type(e).__name__,
                    detail=str(e),
                )
                chunk_embedding.save()

                self.stdout.write(
                    self.style.ERROR(
                        f"  [{i}/{total}] ✗ {chunk_embedding.chunk_id}: {str(e)}"
                    )
                )

        self.stdout.write("\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Complete: {success_count} success, {error_count} errors"
            )
        )

    def show_stats(self, options):
        """Show embedding statistics"""
        library_id = options.get("library")

        library = None
        if library_id:
            try:
                library = Library.objects.get(id=library_id)
                self.stdout.write(f"Library: {library.name}\n")
            except Library.DoesNotExist:
                raise CommandError(f"Library {library_id} not found")

        # Get stats
        stats = get_embedding_stats(library=library)

        self.stdout.write(self.style.SUCCESS("📊 Embedding Statistics\n"))
        self.stdout.write(f"Total:    {stats['total']}")
        self.stdout.write(f"Pending:  {stats['pending']}")
        self.stdout.write(f"Complete: {stats['complete']}")
        self.stdout.write(f"Failed:   {stats['failed']}")

        # Check for stale
        if library:
            stale = get_stale_embeddings(library=library)
            if stale:
                self.stdout.write(
                    self.style.WARNING(f"\n⚠️  Stale:    {len(stale)}")
                )
                self.stdout.write(
                    "   (Run with --mark-stale to mark for re-embedding)"
                )

    def mark_stale(self, options):
        """Mark stale embeddings as pending"""
        library_id = options.get("library")

        library = None
        if library_id:
            try:
                library = Library.objects.get(id=library_id)
            except Library.DoesNotExist:
                raise CommandError(f"Library {library_id} not found")

        self.stdout.write("🔍 Checking for stale embeddings...")

        count = mark_stale_embeddings_pending(library=library)

        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Marked {count} stale embeddings as PENDING"
                )
            )
        else:
            self.stdout.write("✓ No stale embeddings found")
