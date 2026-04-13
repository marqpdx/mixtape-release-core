# stackroom/django_client/client.py
#
# Shadow-mode REST client for the standalone Stackroom service.
# CP3: fire-and-forget calls alongside existing ORM calls for latency measurement.
# Responses are always discarded. Auth is deferred to CP4 (real cutover).

import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger("stackroom.shadow")

SHADOW_TIMEOUT = 5  # seconds — must not block the request path


def _base_url() -> str:
    return getattr(settings, "STACKROOM_BASE_URL", "http://127.0.0.1:8012").rstrip("/")


def _shadow(label: str, method: str, path: str, **kwargs) -> None:
    """Fire a REST call to the standalone Stackroom service in a daemon thread.

    Result is always discarded. Logs label, HTTP status, and elapsed_ms.
    Never raises — all exceptions are caught and logged.
    """
    def _call():
        url = f"{_base_url()}{path}"
        start = time.monotonic()
        try:
            resp = requests.request(method, url, timeout=SHADOW_TIMEOUT, **kwargs)
            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                "stackroom_shadow label=%s method=%s path=%s status=%s elapsed_ms=%.1f",
                label, method, path, resp.status_code, elapsed,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning(
                "stackroom_shadow label=%s method=%s path=%s error=%r elapsed_ms=%.1f",
                label, method, path, exc, elapsed,
            )

    threading.Thread(target=_call, daemon=True).start()


def shadow_user_shelves(user_id, visibility: list, scope: str = "writing") -> None:
    """Site 8 — PublicMemberShelvesView.
    Calls GET /libraries/public (no auth required).
    """
    _shadow(
        "user_shelves",
        "GET",
        "/libraries/public",
        params={"sponsor_id": str(user_id), "visibility": ",".join(visibility), "scope": scope},
    )


def shadow_available_libraries(group_id) -> None:
    """Site 4 — earthlab list_available_content.
    Calls GET /libraries with no auth — expects 401 in shadow mode. Tests connectivity + latency.
    """
    _shadow(
        "available_libraries",
        "GET",
        "/libraries",
        params={"sponsor_id": str(group_id)},
    )


def shadow_shelf_ids(shelf_ids: list) -> None:
    """Site 9 — writing publish_service shelves.
    Calls GET /libraries with no auth — expects 401 in shadow mode. Tests connectivity + latency.
    """
    if not shelf_ids:
        return
    _shadow(
        "shelf_ids",
        "GET",
        "/libraries",
        params={"ids": ",".join(str(i) for i in shelf_ids)},
    )
