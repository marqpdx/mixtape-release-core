# inkwell/utils/gutenberg_helpers.py

import logging


logger = logging.getLogger(__name__)

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

def scrape_gutenberg_metadata(source_id: str, keyword: str = "") -> dict:
    try:
        url = f"https://www.gutenberg.org/ebooks/{source_id}"
        soup = BeautifulSoup(session.get(url, timeout=30).text, "html.parser")

        title = soup.select_one("h1.header__title").text.strip()
        author_elem = soup.select_one(".header__subtitle")
        author = author_elem.text.strip() if author_elem else "Unknown"

        text_url = f"https://www.gutenberg.org/files/{source_id}/{source_id}-0.txt"
        cover_url = f"https://www.gutenberg.org/cache/epub/{source_id}/pg{source_id}.cover.medium.jpg"

        return {
            "source_id": source_id,
            "title": title,
            "author": author,
            "cover_url": cover_url,
            "text_url": text_url,
            "source_url": f"/ebooks/{source_id}",
            "subject_tags": [keyword] if keyword else [],
            "source": "gutenberg",
        }
    except Exception as e:
        logger.error(" Failed to scrape Gutenberg metadata for ID {source_id}: %s", e)
        raise


def scrape_gutenberg_metadata_from_result(result, keyword: str) -> dict:
    title = result.select_one(".title").text.strip()
    author_elem = result.select_one(".subtitle")
    author = author_elem.text.strip() if author_elem else "Unknown"

    link = result.find("a")["href"]
    gutenberg_id = link.strip("/").split("/")[-1]

    return {
        "source_id": gutenberg_id,
        "title": title,
        "author": author,
        "source_url": link,
        "cover_url": f"https://www.gutenberg.org/cache/epub/{gutenberg_id}/pg{gutenberg_id}.cover.medium.jpg",
        "text_url": f"https://www.gutenberg.org/files/{gutenberg_id}/{gutenberg_id}-0.txt",
        "subject_tags": [keyword],
        "source": "gutenberg",
    }

def generate_synopsis_if_missing(asset, llm=None):
    if asset.synopsis:
        return

    try:
        if not llm:
            from inkwell.config.llm_config import configure_llm
            llm = configure_llm()

        if not llm:
            logger.warning(" LLM not available — skipping synopsis for %s", asset.title)
            return

        if not hasattr(asset, "gutenberg_info") or not asset.gutenberg_info.text_url:
            logger.warning(" Skipping ingestion: no text_url for asset {asset.id} - '%s'", asset.title)
            return  # or `continue` if in a loop

        text = session.get(asset.gutenberg_info.text_url, timeout=30).text
        short = text[:3000]
        prompt = f"Give a brief synopsis of the following book:\n\n{short}"

        logger.info(" Generating synopsis via LLM for: %s", asset.title)
        response = llm.complete(prompt)
        logger.info(" Received synopsis for: %s", asset.title)

        asset.synopsis = response.text.strip()
        asset.save()
        logger.info(" Synopsis generated for: %s", asset.title)

    except Exception as e:
        logger.error(" Failed to generate synopsis for {asset.title}: %s", e)


