# utils/storage/storage_utils.py

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from django.core.files.storage import default_storage

from mixtape.storage_backends import PublicMediaStorage

_public_storage = PublicMediaStorage()


def is_absolute_url(value: str) -> bool:
    if not value:
        return False
    return bool(urlparse(value).scheme)


def key_to_url(key: Optional[str]) -> Optional[str]:
    """
    Turn a storage key (e.g. 'emblems/<uuid>/size_96.png') into a signed URL
    via the default (access-controlled) storage.
    - If key is already absolute, return as-is.
    - If key is falsy, return None.
    - Otherwise, resolve via default_storage.url().

    Use only for content that is genuinely access-controlled. For content
    visible to anyone who can already see the page it's on, use
    public_key_to_url() instead — see
    reference/patterns/image-handling-cheatsheet.md (puddlejump).
    """
    if not key:
        return None
    if is_absolute_url(key):
        return key
    return default_storage.url(key)


def public_key_to_url(key: Optional[str]) -> Optional[str]:
    """
    Like key_to_url, but resolves through PublicMediaStorage — a stable,
    unsigned URL for content that has been deliberately classified as
    public (visible to anyone who can already see the page it's on).
    Never use this for access-controlled content. See
    reference/patterns/image-handling-cheatsheet.md (puddlejump).
    """
    if not key:
        return None
    if is_absolute_url(key):
        return key
    return _public_storage.url(key)
