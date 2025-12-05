# ai/utils/ingest_thread.py

import logging


logger = logging.getLogger(__name__)

# from inkwell.scripts import ingest_documents_from_url
import os
import threading

import requests
from django.utils import timezone

from inkwell.models import SuggestedAsset


EBOOKS_DIR = os.path.join("ai", "ebooks")
os.makedirs(EBOOKS_DIR, exist_ok=True)

def start_retrieval_agent(suggested_asset: SuggestedAsset):
    def task():
        try:
            response = requests.get(suggested_asset.gutenberg_info.text_url, timeout=30)
            response.raise_for_status()

            filename = f"{suggested_asset.source_id}.txt"
            filepath = os.path.join(EBOOKS_DIR, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(response.text)

            suggested_asset.retrieved = True
            suggested_asset.retrieved_at = timezone.now()
            suggested_asset.save()
            logger.info(" Retrieved: %s", filename)

        except Exception as e:
            logger.error(" Failed to retrieve {suggested_asset.title}: %s", e)

    threading.Thread(target=task, daemon=True).start()
