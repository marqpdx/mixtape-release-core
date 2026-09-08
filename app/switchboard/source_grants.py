from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from django.utils import timezone

from sourcework.models import SourceGrant, SourceGrantStatus
from sourcework.providers import SourceMessage


class SourceGrantAccessError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class SourceGrantReadRequest:
    grant_id: str
    resource_kind: str
    resource_id: str
    limit: int = 5


def fetch_latest_messages_for_source_grant(request: SourceGrantReadRequest, *, user=None) -> list[SourceMessage]:
    """
    Switchboard boundary for external source reads.

    Sourcework and agents pass a SourceGrant handle plus the requested resource.
    Switchboard validates that the request stays inside the grant before any
    provider credential is resolved.
    """
    del user
    grant = (
        SourceGrant.objects.select_related("connection")
        .filter(id=request.grant_id)
        .first()
    )
    if not grant:
        raise SourceGrantAccessError("grant_not_found", "Source Grant not found.")
    _assert_grant_can_read(grant, request)

    if grant.connection.provider == "google_gmail":
        return _fetch_gmail_latest_messages(grant, limit=request.limit)

    raise SourceGrantAccessError("provider_unsupported", f"Provider is not supported: {grant.connection.provider}")


def _assert_grant_can_read(grant: SourceGrant, request: SourceGrantReadRequest) -> None:
    if grant.status != SourceGrantStatus.ACTIVE:
        raise SourceGrantAccessError("grant_inactive", "Source Grant is not active.")
    if grant.revoked_at and grant.revoked_at <= timezone.now():
        raise SourceGrantAccessError("grant_revoked", "Source Grant has been revoked.")
    if grant.connection.revoked_at and grant.connection.revoked_at <= timezone.now():
        raise SourceGrantAccessError("connection_revoked", "External connection has been revoked.")
    if grant.resource_kind != request.resource_kind:
        raise SourceGrantAccessError("resource_kind_denied", "Requested resource kind is outside this Source Grant.")
    if grant.resource_id != request.resource_id:
        raise SourceGrantAccessError("resource_id_denied", "Requested resource is outside this Source Grant.")
    if "read" not in (grant.capabilities or []):
        raise SourceGrantAccessError("capability_denied", "Source Grant does not allow read access.")


def _fetch_gmail_latest_messages(grant: SourceGrant, *, limit: int) -> list[SourceMessage]:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SourceGrantAccessError(
            "provider_dependency_missing",
            "Google Gmail adapter requires google-auth and google-api-python-client.",
        ) from exc

    credentials_payload = _load_credential_payload(grant)
    credentials = Credentials.from_authorized_user_info(credentials_payload, scopes=grant.connection.provider_scopes or None)
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    listed = (
        service.users()
        .messages()
        .list(userId="me", labelIds=[grant.resource_id], maxResults=max(1, min(int(limit or 5), 25)))
        .execute()
    )
    messages = []
    for item in listed.get("messages", []):
        raw = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        messages.append(_gmail_message_to_source_message(raw))
    return messages


def _load_credential_payload(grant: SourceGrant) -> dict:
    raw = grant.connection.credential_payload
    if not raw:
        raise SourceGrantAccessError("credential_missing", "External connection has no credential payload.")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceGrantAccessError("credential_invalid", "External connection credential payload is not valid JSON.") from exc


def _gmail_message_to_source_message(raw: dict) -> SourceMessage:
    headers = {
        header.get("name", "").lower(): header.get("value", "")
        for header in raw.get("payload", {}).get("headers", [])
    }
    return SourceMessage(
        provider_message_id=str(raw.get("id") or ""),
        provider_thread_id=str(raw.get("threadId") or ""),
        from_header=headers.get("from", ""),
        sent_at=headers.get("date", ""),
        subject=headers.get("subject", ""),
        body=_extract_gmail_text(raw.get("payload") or {}),
    )


def _extract_gmail_text(payload: dict) -> str:
    mime_type = payload.get("mimeType") or ""
    body_data = (payload.get("body") or {}).get("data")
    if body_data and mime_type in {"text/plain", "text/html"}:
        return _decode_gmail_body(body_data)
    for part in payload.get("parts") or []:
        text = _extract_gmail_text(part)
        if text:
            return text
    return ""


def _decode_gmail_body(value: str) -> str:
    padded = value + ("=" * (-len(value) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""
