# ai/utils/parse_gutenberg_url_file.py

import logging


logger = logging.getLogger(__name__)

import re
from pathlib import Path

from inkwell.utils.asset_actions import preapprove_asset
from inkwell.utils.asset_creation import create_suggested_asset


def parse_gutenberg_url_file(filepath: str):
    path = Path(filepath)
    if not path.exists():
        logger.error(" File not found: %s", filepath)
        return

    created = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            match = re.search(r"/ebooks/(\d+)", line)
            if not match:
                logger.warning(" Invalid line skipped: %s", line)
                continue

            gutenberg_id = match.group(1)

            data = {
                "source_id": gutenberg_id,
                "source": "gutenberg",
                "asset_type": "book",
                "title": f"Gutenberg #{gutenberg_id}",
                "subject_tags": [],
                "text_url": f"https://www.gutenberg.org/files/{gutenberg_id}/{gutenberg_id}-0.txt",
                "cover_url": f"https://www.gutenberg.org/cache/epub/{gutenberg_id}/pg{gutenberg_id}.cover.medium.jpg",
            }

            asset = create_suggested_asset(data)
            preapprove_asset(asset, trigger_synopsis=True)  # don't start Celery here

            created += 1
            logger.info(" Added: %s", gutenberg_id)

    logger.info("🎉 Created {created} new suggested assets with id: {asset.id}")


