# utils/email/shortcode.py

import base64
from uuid import uuid4


def generate_shortcode():
    # Generate short, URL-safe unique ID (e.g., 6–10 chars)
    return base64.urlsafe_b64encode(uuid4().bytes)[:8].decode().rstrip("=")
