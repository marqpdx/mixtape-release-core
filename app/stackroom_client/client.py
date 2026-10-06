# stackroom_client/client.py
#
# The one HTTP client for Django → Stackroom: service-JWT minting, library
# provisioning, ingest, retrieve, and source-file operations. Consolidates the
# former inkwell/stackroom_http_client.py and initiatives/services/
# agent_stackroom.py (folio-notes-poc-handoff.md addendum §3); both remain as
# re-export shims so existing imports keep working.

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
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        extra: dict | None = None,
        body: str = "",
    ):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}
        self.body = body


def base_url() -> str:
    return getattr(settings, "STACKROOM_BASE_URL", "http://127.0.0.1:8012").rstrip("/")


_base_url = base_url


def mint_service_token(subject: str = "django") -> str:
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    return jwt.encode(
        {
            "sub": subject,
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
            "aud": getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir"),
        },
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


_mint_service_token = mint_service_token


def service_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token()}


_headers = service_headers


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
    artifact_type: str | None = None,
) -> dict:
    """
    POST /libraries/{library_id}/ingest with inline text.
    Returns {source_file_id, run_id, status}.
    409 (same hash already exists) is treated as success — content unchanged.
    artifact_type tags the Stackroom Artifact (retrieve can filter on it);
    omitted, Stackroom uses its default ("extracted_text").
    """
    hash_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    body = {
        "origin": "external",
        "path": source_path,
        "filename": filename,
        "content_type": "text/plain",
        "size_bytes": len(text.encode("utf-8")),
        "hash_sha256": hash_sha256,
        "text": text,
    }
    if artifact_type:
        body["artifact_type"] = artifact_type
    resp = requests.post(
        f"{_base_url()}/libraries/{library_id}/ingest",
        json=body,
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
# Retrieve
# ---------------------------------------------------------------------------

def retrieve(
    *,
    query: str,
    library_id: UUID,
    limit: int = 8,
    artifact_types: list[str] | None = None,
) -> list[dict]:
    """
    Query the Stackroom vector index for a sponsor's library.

    Returns a list of result dicts with keys:
        text, score, artifact_type, artifact_id, source_file_id
    A 400 from Stackroom (no_embeddings / indexing_in_progress) is an empty
    result, not an error. Raises StackroomClientError on any other failure.
    """
    payload: dict = {
        "query": query,
        "library_id": str(library_id),
        "limit": limit,
    }
    if artifact_types:
        payload["artifact_types"] = artifact_types

    try:
        response = requests.post(
            f"{_base_url()}/service/retrieve",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
    except requests.exceptions.ReadTimeout as exc:
        raise StackroomClientError("Stackroom retrieve timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise StackroomClientError(f"Stackroom unreachable: {exc}", status_code=502) from exc

    if response.status_code == 400:
        return []
    if response.status_code != 200:
        raise StackroomClientError(
            "Stackroom error",
            status_code=response.status_code,
            body=response.text,
        )

    data = response.json()
    return [
        {
            "text": r.get("text", ""),
            "score": r.get("score", 0.0),
            "artifact_type": r.get("artifact_type", ""),
            "artifact_id": r.get("artifact_id", ""),
            "source_file_id": r.get("source_file_id", ""),
        }
        for r in data.get("results", [])
    ]


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


def get_source_file_metadata(source_file_id: UUID) -> dict:
    """GET /source-files/{source_file_id}."""
    resp = requests.get(
        f"{_base_url()}/source-files/{source_file_id}",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise StackroomClientError(
            f"Source file metadata failed: {resp.status_code} {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json()


def get_source_file_readable(source_file_id: UUID) -> dict:
    """GET /source-files/{source_file_id}/readable."""
    resp = requests.get(
        f"{_base_url()}/source-files/{source_file_id}/readable",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise StackroomClientError(
            f"Source file readable failed: {resp.status_code} {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json()


def download_source_file(source_file_id: UUID) -> tuple[bytes, dict]:
    """GET /source-files/{source_file_id}/download."""
    resp = requests.get(
        f"{_base_url()}/source-files/{source_file_id}/download",
        headers=_headers(),
        timeout=60,
    )
    if resp.status_code != 200:
        raise StackroomClientError(
            f"Source file download failed: {resp.status_code} {resp.text}",
            status_code=resp.status_code,
    )
    return resp.content, dict(resp.headers)


def preview_source_file_pdf(source_file_id: UUID) -> tuple[bytes, dict]:
    """GET /source-files/{source_file_id}/preview.pdf."""
    resp = requests.get(
        f"{_base_url()}/source-files/{source_file_id}/preview.pdf",
        headers=_headers(),
        timeout=90,
    )
    if resp.status_code != 200:
        raise StackroomClientError(
            f"Source file preview failed: {resp.status_code} {resp.text}",
            status_code=resp.status_code,
        )
    return resp.content, dict(resp.headers)


def upload_library_file(library_id: UUID, file_bytes: bytes, filename: str, content_type: str) -> dict:
    """
    POST /libraries/{library_id}/upload
    Returns: { source_file_id, filename, status }
    Raises StackroomClientError with status_code=409 if file already exists.
    """
    resp = requests.post(
        f"{_base_url()}/libraries/{library_id}/upload",
        headers=_headers(),
        files={"file": (filename, file_bytes, content_type)},
        timeout=60,
    )
    if resp.status_code == 201:
        return resp.json()
    if resp.status_code == 409:
        existing_id = resp.headers.get("X-Source-File-Id")
        raise StackroomClientError(
            "File already exists in this library",
            status_code=409,
            extra={"source_file_id": existing_id},
        )
    raise StackroomClientError(
        f"Upload failed: {resp.status_code} {resp.text}",
        status_code=resp.status_code,
    )


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
