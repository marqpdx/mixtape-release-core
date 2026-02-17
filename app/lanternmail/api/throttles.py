from __future__ import annotations

from typing import Optional

from rest_framework.throttling import SimpleRateThrottle


class NewsletterIPThrottle(SimpleRateThrottle):
    scope = "newsletter_ip"
    rate = "20/hour"

    def get_cache_key(self, request, view) -> Optional[str]:
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}


class NewsletterEmailThrottle(SimpleRateThrottle):
    scope = "newsletter_email"
    rate = "5/hour"

    def get_cache_key(self, request, view) -> Optional[str]:
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}
