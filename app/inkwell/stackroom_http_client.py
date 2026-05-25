# inkwell/stackroom_http_client.py
#
# HTTP client for Django → Stackroom service communication.
# Handles library provisioning, ingest, and source-file deletion.
# Pattern: agent_stackroom.py (existing retrieval client).

from __future__ import annotations

import hashlib
import logging
import time
from uuid import UUID

import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class StackroomClientError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _base_url() -> str:
    return getattr(settings, "STACKROOM_BASE_URL", "http://127.0.0.1:8012").rstrip("/")


def _mint_service_token() -> str:
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    return jwt.encode(
        {
            "sub": "django",
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
            "aud": getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir"),
        },
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


def _headers() -> dict[str, str]:
    return {"X-Service-Token": _mint_service_token()}


# ---------------------------------------------------------------------------
# Library provisioning
# ---------------------------------------------------------------------------

def get_or_create_user_library(user) -> UUID:
    """Return the Stackroom library UUID for a user, creating it if needed."""
    if user.stackroom_library_id:
        return user.stackroom_library_id

    lib_id = _create_library(
        title=f"{user.username}'s Library",
        sponsor_type="user",
        sponsor_id=user.pk,
    )
    type(user).objects.filter(pk=user.pk).update(stackroom_library_id=lib_id)
    user.stackroom_library_id = lib_id
    return lib_id


def get_or_create_group_library(group) -> UUID:
    """Return the Stackroom library UUID for a group, creating it if needed."""
    if group.stackroom_library_id:
        return group.stackroom_library_id

    lib_id = _create_library(
        title=f"{group.title}'s Library",
        sponsor_type="group",
        sponsor_id=group.pk,
    )
    type(group).objects.filter(pk=group.pk).update(stackroom_library_id=lib_id)
    group.stackroom_library_id = lib_id
    return lib_id


def _create_library(*, title: str, sponsor_type: str, sponsor_id) -> UUID:
    resp = requests.post(
        f"{_base_url()}/libraries",
        json={"title": title, "sponsor_type": sponsor_type, "sponsor_id": str(sponsor_id)},
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise StackroomClientError(
            f"Library create failed: {resp.status_code} {resp.text}", status_code=resp.status_code
        )
    return UUID(resp.json()["id"])


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_text(
    *,
    library_id: UUID,
    source_path: str,
    filename: str,
    text: str,
) -> dict:
    """
    POST /libraries/{library_id}/ingest with inline text.
    Returns {source_file_id, run_id, status}.
    409 (same hash already exists) is treated as success — content unchanged.
    """
    hash_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    resp = requests.post(
        f"{_base_url()}/libraries/{library_id}/ingest",
        json={
            "origin": "external",
            "path": source_path,
            "filename": filename,
            "content_type": "text/plain",
            "size_bytes": len(text.encode("utf-8")),
            "hash_sha256": hash_sha256,
            "text": text,
        },
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code == 409:
        return {"hash_sha256": hash_sha256, "already_current": True}
    if resp.status_code not in (200, 201):
        raise StackroomClientError(
            f"Ingest failed: {resp.status_code} {resp.text}", status_code=resp.status_code
        )
    data = resp.json()
    data["hash_sha256"] = hash_sha256
    return data


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------

def get_library_source_files(library_id: UUID) -> list[dict]:
    """
    GET /libraries/{library_id}/source-files
    Returns a list of source file dicts: id, filename, content_type,
    size_bytes, origin, created_at.
    """
    resp = requests.get(
        f"{_base_url()}/libraries/{library_id}/source-files",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        raise StackroomClientError(
            f"Source file list failed: {resp.status_code} {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json().get("files", [])


def delete_source_file(source_file_id: UUID) -> None:
    """DELETE /source-files/{source_file_id} — remove from Stackroom IR."""
    resp = requests.delete(
        f"{_base_url()}/source-files/{source_file_id}",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code in (200, 204, 404):
        return
    raise StackroomClientError(
        f"Source file delete failed: {resp.status_code} {resp.text}",
        status_code=resp.status_code,
    )
