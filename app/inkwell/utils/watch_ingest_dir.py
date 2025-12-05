# ai/utils/watch_ingest_dir.py

import logging


logger = logging.getLogger(__name__)

import shutil
import time
from pathlib import Path

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
            shutil.move(str(path), PROCESSED_DIR / path.name)
            logger.info(" Processed and moved: %s", path.name)
        except Exception as e:
            logger.error(" Error processing {path.name}: %s", e)


def start_watchdog():
    logger.info("👀 Watching for .txt files in {WATCH_DIR}")
    observer = Observer()
    handler = IngestTextFileHandler()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("🛑 Watchdog stopped.")
        observer.stop()
    observer.join()

