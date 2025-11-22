# utils/email/shortcode.py

from uuid import uuid4
import base64

def generate_shortcode():
    # Generate short, URL-safe unique ID (e.g., 6–10 chars)
    return base64.urlsafe_b64encode(uuid4().bytes)[:8].decode().rstrip("=")