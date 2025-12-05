import logging


logger = logging.getLogger(__name__)

import shutil
import time
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from inkwell.utils.parse_gutenberg_url_file import parse_gutenberg_url_file


WATCH_DIR = Path("ai/ebooks/to_ingest")
PROCESSED_DIR = Path("ai/ebooks/processed")

class IngestTextFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix != ".txt":
            return

        logger.info("📄 Detected file: {path.name}")
        try:
            parse_gutenberg_url_file(str(path))
            PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y-%m-%d")
            renamed_name = f"aa_ingested_{timestamp}_{path.name}"
            renamed_path = PROCESSED_DIR / renamed_name
            shutil.move(str(path), renamed_path)
            logger.info(" Processed and moved: %s", renamed_path.name)
        except Exception as e:
            logger.error(" Error processing {path.name}: %s", e)


class Command(BaseCommand):
    help = "Watches the ebook ingestion directory for .txt URL lists"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS(f"👀 Watching for files in {WATCH_DIR}"))
        observer = Observer()
        handler = IngestTextFileHandler()
        observer.schedule(handler, str(WATCH_DIR), recursive=False)
        observer.start()

        try:
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
