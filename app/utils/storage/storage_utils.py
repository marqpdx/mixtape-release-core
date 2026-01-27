# utils/storage/storage_utils.py

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from django.core.files.storage import default_storage


def is_absolute_url(value: str) -> bool:
    if not value:
        return False
    return bool(urlparse(value).scheme)


def key_to_url(key: Optional[str]) -> Optional[str]:
    """
    Turn a storage key (e.g. 'emblems/<uuid>/size_96.png') into a public URL.
    - If key is already absolute, return as-is.
    - If key is falsy, return None.
    - Otherwise, resolve via default_storage.url().
    """
    if not key:
        return None
    if is_absolute_url(key):
        return key
    return default_storage.url(key)
