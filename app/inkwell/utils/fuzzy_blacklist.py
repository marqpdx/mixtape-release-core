# ai/utils/fuzzy_blacklist.py

import logging


logger = logging.getLogger(__name__)

from rapidfuzz import fuzz

from inkwell.models import BlacklistedTitle


def blacklist_title(title: str, reason: str = "") -> BlacklistedTitle:
    from inkwell.models import BlacklistedTitle

    obj, created = BlacklistedTitle.objects.get_or_create(loose_title=title)
    if created:
        obj.reason = reason
        obj.save()
        logger.info("🛡️ Blacklisted new title: '{title}' — Reason: {reason}")
    else:
        logger.warning(" Title already in blacklist: '%s'", title)
    return obj


def is_title_blacklisted(candidate_title: str, candidate_author: str = "", threshold: int = 85) -> bool:
    blacklisted_titles = BlacklistedTitle.objects.values_list("loose_title", flat=True)
    combined = f"{candidate_author} {candidate_title}".strip().lower()

    for blacklisted in blacklisted_titles:
        score = fuzz.token_set_ratio(combined, blacklisted.lower())
        if score >= threshold:
            logger.info("🛑 Blocked '{combined}' (matched '{blacklisted}' at {score}%)")
            return True
    return False
