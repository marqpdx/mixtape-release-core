from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sourcework.models import SourceGrant


@dataclass(frozen=True)
class SourceMessage:
    """
    Provider-neutral message envelope used by Sourcework import services.

    Provider adapters should normalize external payloads into this shape before
    SourceEvidence and ProvisionalData records are created.
    """

    provider_message_id: str = ""
    provider_thread_id: str = ""
    from_header: str = ""
    sender_header: str = ""
    sender_display_name: str = ""
    sender_email: str = ""
    sent_at: str = ""
    subject: str = ""
    body: str = ""

    @classmethod
    def from_mapping(cls, value: dict) -> "SourceMessage":
        return cls(
            provider_message_id=str(value.get("provider_message_id") or value.get("id") or ""),
            provider_thread_id=str(value.get("provider_thread_id") or value.get("thread_id") or ""),
            from_header=str(value.get("from") or value.get("from_header") or ""),
            sender_header=str(value.get("sender_header") or ""),
            sender_display_name=str(value.get("sender_display_name") or ""),
            sender_email=str(value.get("sender_email") or ""),
            sent_at=str(value.get("sent_at") or value.get("date") or ""),
            subject=str(value.get("subject") or ""),
            body=str(value.get("body") or ""),
        )

    def as_import_payload(self) -> dict:
        return {
            "provider_message_id": self.provider_message_id,
            "provider_thread_id": self.provider_thread_id,
            "from_header": self.from_header,
            "sender_header": self.sender_header,
            "sender_display_name": self.sender_display_name,
            "sender_email": self.sender_email,
            "sent_at": self.sent_at,
            "subject": self.subject,
            "body": self.body,
        }


class SourceProviderAdapter(Protocol):
    adapter_key: str

    def fetch_latest_messages(self, source_grant: SourceGrant, *, limit: int = 5, payload: dict | None = None) -> list[SourceMessage]:
        ...


class ManualMessageAdapter:
    """
    Temporary provider adapter for operator-supplied Gmail-shaped payloads.

    This keeps the latest-5 proof path on the same adapter contract the Gmail
    and IMAP readers will implement later.
    """

    adapter_key = "manual_v1"

    def fetch_latest_messages(self, source_grant: SourceGrant, *, limit: int = 5, payload: dict | None = None) -> list[SourceMessage]:
        del source_grant
        payload = payload or {}
        messages = payload.get("messages") or []
        return [SourceMessage.from_mapping(message) for message in messages[:limit]]


class SwitchboardGmailAdapter:
    """
    Credential-backed Gmail reader routed through Switchboard.

    Sourcework keeps the import pipeline; Switchboard owns SourceGrant
    enforcement and provider credential resolution.
    """

    adapter_key = "switchboard_gmail_v1"

    def fetch_latest_messages(self, source_grant: SourceGrant, *, limit: int = 5, payload: dict | None = None) -> list[SourceMessage]:
        del payload
        from switchboard.source_grants import SourceGrantReadRequest, fetch_latest_messages_for_source_grant

        return fetch_latest_messages_for_source_grant(
            SourceGrantReadRequest(
                grant_id=str(source_grant.id),
                resource_kind=source_grant.resource_kind,
                resource_id=source_grant.resource_id,
                limit=limit,
            )
        )


ADAPTERS: dict[str, SourceProviderAdapter] = {
    ManualMessageAdapter.adapter_key: ManualMessageAdapter(),
    SwitchboardGmailAdapter.adapter_key: SwitchboardGmailAdapter(),
}


def get_source_provider_adapter(adapter_key: str) -> SourceProviderAdapter:
    try:
        return ADAPTERS[adapter_key]
    except KeyError as exc:
        raise ValueError(f"Unknown source provider adapter: {adapter_key}") from exc
