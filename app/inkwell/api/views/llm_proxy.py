# app/inkwell/api/views/llm_proxy.py

import logging
import requests

from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated  # or AllowAny if you prefer
from rest_framework import status

logger = logging.getLogger(__name__)

INKWELL_BASE_URL = getattr(settings, "INKWELL_BASE_URL", "").rstrip("/") or "https://inkwell.crossroads.place"


# ---------- /v1/normalize-tiptap ----------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def normalize_tiptap_proxy(request):
    """
    Proxy to Inkwell /v1/normalize-tiptap.
    Expects { doc: ... } and returns { plaintext, normalized } unchanged.
    """


    inkwell_normalize_tiptap_url = f"{INKWELL_BASE_URL}/v1/normalize-tiptap"
    print("Inkwell normalize tiptap URL:", inkwell_normalize_tiptap_url)


    try:
        upstream = requests.post(
            inkwell_normalize_tiptap_url,
            json=request.data,
            timeout=30,
        )
    except requests.RequestException as e:
        logger.exception("Error calling Inkwell /v1/normalize-tiptap")
        return JsonResponse(
            {"detail": f"Inkwell unreachable: {e}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if upstream.status_code != 200:
        body = upstream.text
        logger.error("Inkwell /v1/normalize-tiptap error %s: %s", upstream.status_code, body[:500])
        return JsonResponse(
            {
                "detail": "Inkwell error",
                "status_code": upstream.status_code,
                "body": body,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Pass through the JSON as-is
    return JsonResponse(upstream.json(), status=status.HTTP_200_OK)


# ---------- /v1/summarize/quick ----------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def summarize_quick_proxy(request):
    """
    Proxy to Inkwell /v1/summarize/quick.
    Expects { text, words, style } and returns { summary, ... } unchanged.
    """
    try:
        upstream = requests.post(
            f"{INKWELL_BASE_URL}/v1/summarize/quick",
            json=request.data,
            timeout=180,  # a bit higher since summarization can be heavier
        )
    except requests.RequestException as e:
        logger.exception("Error calling Inkwell /v1/summarize/quick")
        return JsonResponse(
            {"detail": f"Inkwell unreachable: {e}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if upstream.status_code != 200:
        body = upstream.text
        logger.error("Inkwell /v1/summarize/quick error %s: %s", upstream.status_code, body[:500])
        return JsonResponse(
            {
                "detail": "Inkwell error",
                "status_code": upstream.status_code,
                "body": body,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return JsonResponse(upstream.json(), status=status.HTTP_200_OK)


# ---------- /v1/edit (SSE streaming) ----------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def edit_stream_proxy(request):
    """
    Proxy streaming SSE from Inkwell /v1/edit to the browser.
    Keeps the exact SSE event stream shape.
    """
    try:
        upstream = requests.post(
            f"{INKWELL_BASE_URL}/v1/edit",
            json=request.data,
            stream=True,  # important: don't buffer
            timeout=None, # let the upstream control duration
        )
    except requests.RequestException as e:
        logger.exception("Error calling Inkwell /v1/edit")
        return JsonResponse(
            {"detail": f"Inkwell unreachable: {e}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if upstream.status_code != 200:
        body = upstream.text
        logger.error("Inkwell /v1/edit error %s: %s", upstream.status_code, body[:500])
        return JsonResponse(
            {
                "detail": "Inkwell error",
                "status_code": upstream.status_code,
                "body": body,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    def event_stream():
        try:
            for chunk in upstream.iter_content(chunk_size=1024):
                if chunk:
                    # Just relay bytes; they’re already in SSE format
                    yield chunk
        finally:
            upstream.close()

    resp = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # avoid buffering in nginx
    return resp
