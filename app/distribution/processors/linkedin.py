# distribution/processors/linkedin.py
"""
LinkedInProcessor — records a LinkedIn share action.

LinkedIn does not provide a write API for personal posts in the standard
third-party OAuth flow. This processor:
  1. Captures the canonical URL at share time.
  2. Builds a LinkedIn share dialog URL (share-offsite pattern).
  3. Stores optional author post copy in channel_config.
  4. Returns a ShareRecord with status='success' and the share URL in
     channel_response.linkedin_share_url.

The frontend presents "Copy post copy" + "Open LinkedIn →" after publish.
Tier required: community.
"""

import logging
from urllib.parse import urlencode, quote_plus

logger = logging.getLogger(__name__)

LINKEDIN_SHARE_BASE = "https://www.linkedin.com/sharing/share-offsite/"


def _build_canonical_url(piece) -> str:
    if piece.canonical_url:
        return piece.canonical_url

    from django.conf import settings
    base = getattr(settings, "SITE_BASE_URL", "https://mixtape.social")

    # Always use the public /writing/<slug> route.
    # The group-scoped URL (/groups/<slug>/writing/<slug>) requires authentication
    # and would present a login wall to LinkedIn readers who aren't Mixtape members.
    return f"{base}/writing/{piece.slug}"


class LinkedInProcessor:
    source_kind = "linkedin"

    def validate_config(self, config: dict) -> list[str]:
        # post_copy is optional; nothing required
        return []

    def process(self, piece, source, config: dict) -> dict:
        canonical_url = _build_canonical_url(piece)
        og_title = piece.title or "Untitled"
        synopsis = getattr(piece, "excerpt", "") or ""
        og_image = ""
        post_copy = config.get("post_copy", "")

        result = {
            "status": "success",
            "canonical_url": canonical_url,
            "og_title": og_title,
            "synopsis": synopsis,
            "og_image": og_image,
            "channel_config": {**config, "post_copy": post_copy},
            "channel_response": {},
            "failure_reason": "",
        }

        if not canonical_url:
            result["status"] = "failed"
            result["failure_reason"] = "canonical_url could not be determined"
            return result

        try:
            share_url = LINKEDIN_SHARE_BASE + "?" + urlencode({"url": canonical_url})
            result["channel_response"] = {
                "linkedin_share_url": share_url,
                "post_copy": post_copy,
            }
        except Exception as exc:
            logger.exception("LinkedInProcessor.process failed: %s", exc)
            result["status"] = "failed"
            result["failure_reason"] = str(exc)

        return result
