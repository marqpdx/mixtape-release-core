# inkwell/utils/gutenberg_scraper.py

import logging


logger = logging.getLogger(__name__)

import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from inkwell.models import SuggestedAsset
from inkwell.tasks.synopsis import generate_synopsis_task
from inkwell.utils.asset_creation import create_suggested_asset
from inkwell.utils.gutenberg_helpers import scrape_gutenberg_metadata_from_result


# from inkwell.config.custom_settings import Settings

# Configure requests session with retry logic
session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)

def get_gutenberg_suggestions(keywords, limit, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    results = []
    logger.info("Searching for keywords: %s", keywords)

    for keyword in keywords:
        url = f"https://www.gutenberg.org/ebooks/search/?query={keyword}"

        start = time.time()
        soup = BeautifulSoup(session.get(url, timeout=30).text, "html.parser")
        logger.info("Request to %s took %.2f seconds in get_gutenberg_suggestions", url, time.time() - start)

        for result in soup.select(".booklink"):

            if len(results) >= limit:
                break

            try:
                data = scrape_gutenberg_metadata_from_result(result, keyword)
                if data["source_id"] in exclude_ids:
                    continue
                results.append(data)
            except Exception as e:
                logger.warning(" Skipping result due to parse error: %s", e)

    return results


def create_suggested_asset_from_url(url: str) -> SuggestedAsset:
    if "gutenberg.org" in url:
        match = re.search(r"/ebooks/(\d+)", url)
        if not match:
            raise ValueError("Invalid Gutenberg URL")
        gutenberg_id = match.group(1)

        if SuggestedAsset.objects.filter(source="gutenberg", source_id=gutenberg_id).exists():
            raise ValueError("Asset already exists")

        # ✅ Perform a focused search that returns one result
        search_url = f"https://www.gutenberg.org/ebooks/search/?query={gutenberg_id}"
        soup = BeautifulSoup(session.get(search_url, timeout=30).text, "html.parser")
        result = soup.select_one(".booklink")
        if not result:
            raise ValueError("Gutenberg metadata not found")

        # ✅ Extract structured metadata
        from .gutenberg_helpers import scrape_gutenberg_metadata_from_result
        metadata = scrape_gutenberg_metadata_from_result(result, keyword="manual")  # optional tag

        # ✅ Create SuggestedAsset
        asset = create_suggested_asset(metadata)
        asset.approved = True
        asset.save()

        # if settings.DJANGO_ENV == "prod":
        if True:
            logger.info(" Triggering synopsis for asset: %s", asset.id)
            generate_synopsis_task.delay(asset.id)
        else:
            logger.info("⚠️ Skipping synopsis generation — not in production")

        return asset

    raise ValueError("Unsupported URL source")





# def create_suggested_asset_from_url(url: str) -> SuggestedAsset:
#     if "gutenberg.org" in url:
#         match = re.search(r"/ebooks/(\d+)", url)
#         if not match:
#             raise ValueError("Invalid Gutenberg URL")
#         gutenberg_id = match.group(1)

#         if SuggestedAsset.objects.filter(source="gutenberg", source_id=gutenberg_id).exists():
#             raise ValueError("Asset already exists")

#         asset_data = scrape_gutenberg_metadata(gutenberg_id)

#         asset = create_suggested_asset(asset_data)
#         asset.approved = True
#         asset.save()

#         if settings.DJANGO_ENV == 'prod':
#             generate_synopsis_task.delay(asset.id)

#         return asset

#     raise ValueError("Unsupported URL source")





# def create_suggested_asset_from_url(url: str) -> SuggestedAsset:
#     if "gutenberg.org" in url:
#         match = re.search(r"/ebooks/(\d+)", url)
#         if not match:
#             raise ValueError("Invalid Gutenberg URL")
#         gutenberg_id = match.group(1)

#         # Prevent duplicates
#         if SuggestedAsset.objects.filter(source="gutenberg", source_id=gutenberg_id).exists():
#             raise ValueError("Asset already exists")

#         # Build asset data from existing logic
#         asset_data = {
#             "source": "gutenberg",
#             "source_id": gutenberg_id,
#             "source_url": f"/ebooks/{gutenberg_id}",
#         }

#         asset = create_suggested_asset(asset_data)
#         asset.approved = True
#         asset.save()

#         if settings.DJANGO_ENV == 'prod':
#             logger.info(" Triggering synopsis for asset: %s", asset.id)
#             generate_synopsis_task.delay(asset.id)
#         else:
#             logger.info("⚠️ Skipping synopsis generation — not in production")

#         return asset

#     raise ValueError("Unsupported URL source")
