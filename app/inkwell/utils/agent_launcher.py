# inkwell/utils/agent_launcher.py

import logging
import threading

from inkwell.models import SuggestedAsset
from inkwell.utils.filters import get_excluded_source_ids
from inkwell.utils.gutenberg_scraper import get_gutenberg_suggestions


logger = logging.getLogger(__name__)

def launch_agents_for_task(task):
    def agent_worker(keywords):
        try:
            exclude_ids = get_excluded_source_ids(["gutenberg", "webpage"])
            suggestions = get_gutenberg_suggestions(keywords, task.books_per_agent, exclude_ids=exclude_ids)

            for book in suggestions:
                SuggestedAsset.objects.get_or_create(**book)

            logger.info("Agent worker completed for keywords: %s", keywords)
        except Exception as e:
            logger.error("Agent worker failed for keywords %s: %s", keywords, e, exc_info=True)

    for keyword_set in task.keyword_list:
        t = threading.Thread(target=agent_worker, args=(keyword_set,))
        t.daemon = True
        t.start()
        logger.debug("Started agent thread for keyword set: %s", keyword_set)
