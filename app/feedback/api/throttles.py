from __future__ import annotations

from typing import Optional

from rest_framework.throttling import SimpleRateThrottle


class FeedbackIPThrottle(SimpleRateThrottle):
    scope = "feedback_ip"
    rate = "20/hour"

    def get_cache_key(self, request, view) -> Optional[str]:
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}
