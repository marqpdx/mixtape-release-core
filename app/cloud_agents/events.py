"""Wire-format helpers for agent streaming events."""

from __future__ import annotations

import json


def sse_event(event_type: str, **payload) -> bytes:
    """Encode one normalized cloud-agent event as an SSE data chunk."""
    body = {"type": event_type, **payload}
    return f"data: {json.dumps(body)}\n\n".encode()

