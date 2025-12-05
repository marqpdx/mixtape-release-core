# to run:
# python manage.py show_book_count
# to override Qdrant location:
# python manage.py show_book_count --collection gutenberg25 --qdrant-url http://localhost:6333



from django.core.management.base import BaseCommand
from qdrant_client import QdrantClient

from inkwell.models import IngestedFile


class Command(BaseCommand):
    help = "Shows the number of unique books ingested vs stored in Qdrant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--collection", type=str, default="gutenberg25",
            help="Qdrant collection name to check (default: gutenberg25)"
        )
        parser.add_argument(
            "--qdrant-url", type=str, default="http://localhost:6333",
            help="Qdrant URL (default: http://localhost:6333)"
        )

    def handle(self, *args, **options):
        collection = options["collection"]
        qdrant_url = options["qdrant_url"]

        # DB count and filenames
        db_files = IngestedFile.objects.filter(collection_name=collection).values_list("filepath", flat=True)
        db_files_set = set(db_files)
        db_count = len(db_files_set)
        logger.info("📚 IngestedFile DB count: {db_count}")
        logger.info("📝 Files in DB:")
        for f in sorted(db_files_set):
            logger.info("  • {f}")

        # Qdrant count
        client = QdrantClient(qdrant_url)
        all_qdrant_files = set()
        offset = None

        logger.info("🔍 Scanning Qdrant payloads...")
        while True:
            scroll_result, offset = client.scroll(
                collection_name=collection,
                with_payload=True,
                limit=500,
                offset=offset,
            )

            if not scroll_result:
                break

            for point in scroll_result:
                payload = point.payload or {}
                if "filename" in payload:
                    all_qdrant_files.add(payload["filename"])

            if offset is None:
                break  # ✅ Done scrolling

        logger.info("📦 Qdrant unique filenames: {len(all_qdrant_files)}")
        logger.info("📁 Files in Qdrant:")
        for f in sorted(all_qdrant_files):
            logger.info("  • {f}")

        # Compare
        if db_count == len(all_qdrant_files):
            logger.info("✅ Book counts match.")
        else:
            logger.info("⚠️ Mismatch: check for missing entries in DB or Qdrant.")
