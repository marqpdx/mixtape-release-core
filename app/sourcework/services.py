import hashlib
import re
from dataclasses import dataclass
from email.utils import parseaddr, parsedate_to_datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from groups.models import Group
from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)
from sourcework.models import (
    NameConfidence,
    NameSource,
    NameStatus,
    ProvisionalData,
    ProvisionalDataMembership,
    ProvisionalDataState,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
    WorkingSetStatus,
)
from sourcework.providers import get_source_provider_adapter


_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")

SIGNOFF_PHRASES = [
    "best",
    "best regards",
    "regards",
    "sincerely",
    "thank you",
    "thanks",
    "warmly",
    "cheers",
    "kind regards",
    "respectfully",
]

GENERIC_HEADER_NAMES = {
    "recruiting",
    "recruiter",
    "talent",
    "talent acquisition",
    "jobs",
    "careers",
    "staffing",
    "no reply",
    "noreply",
}


@dataclass
class NameResolution:
    preferred_name: str
    email: str
    source: str
    confidence: str
    status: str
    evidence_excerpt: str = ""


def default_recruiter_working_set(group: Group, user, initiative=None) -> WorkingSet:
    working_set, _ = WorkingSet.objects.get_or_create(
        group=group,
        initiative=initiative,
        title="Recruiter Reconnection",
        defaults={
            "purpose": "Provisional person-like records assembled from bounded recruiter correspondence.",
            "status": WorkingSetStatus.ACTIVE,
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    return working_set


def import_latest_messages(source_grant: SourceGrant, messages: list[dict], *, user) -> dict:
    """
    Import bounded Gmail-like message metadata into source evidence and
    provisional recruiter contact records. The caller is responsible for
    ensuring the messages came through the SourceGrant/Switchboard boundary.
    """
    group = source_grant.connection.group
    working_set = default_recruiter_working_set(group, user, source_grant.initiative)

    imported = 0
    reused = 0
    provisional_created = 0
    provisional_reused = 0

    for position, message in enumerate(messages):
        provider_message_id = str(message.get("provider_message_id") or message.get("id") or "").strip()
        if not provider_message_id:
            provider_message_id = _message_fingerprint(source_grant, message)

        resolution = resolve_sender_name(message)
        sent_at = _parse_sent_at(message.get("sent_at") or message.get("date"))
        source_fingerprint = _message_fingerprint(source_grant, {**message, "provider_message_id": provider_message_id})

        with transaction.atomic():
            evidence, evidence_created = SourceEvidence.objects.update_or_create(
                source_grant=source_grant,
                provider_message_id=provider_message_id,
                defaults={
                    "provider": source_grant.connection.provider,
                    "provider_thread_id": str(message.get("provider_thread_id") or message.get("thread_id") or ""),
                    "label_id": source_grant.resource_id,
                    "sender_email": resolution.email,
                    "sender_display_name_raw": str(message.get("sender_display_name") or ""),
                    "sender_header_raw": str(message.get("from") or message.get("from_header") or message.get("sender_header") or ""),
                    "sent_at": sent_at,
                    "subject": str(message.get("subject") or ""),
                    "source_fingerprint": source_fingerprint,
                    "body_snapshot_status": "signature_excerpt" if resolution.evidence_excerpt else "not_stored",
                    "bounded_excerpt": resolution.evidence_excerpt,
                    "metadata": {
                        "name_resolution": {
                            "source": resolution.source,
                            "confidence": resolution.confidence,
                            "status": resolution.status,
                        }
                    },
                },
            )

            record = _find_existing_recruiter_contact(group, resolution.email)
            if record:
                provisional_reused += 1
                if record.state == ProvisionalDataState.REJECTED:
                    continue  # never re-surface a rejected contact
                _apply_name_resolution(record, resolution, user=user, update_existing=True)
            else:
                record = ProvisionalData.objects.create(
                    group=group,
                    kind="recruiter_contact",
                    source_type=source_grant.connection.provider,
                    source_external_id=provider_message_id,
                    captured_at=timezone.now(),
                    observed_at=sent_at,
                    state=ProvisionalDataState.NEW,
                    source_evidence=evidence,
                    owner_user=user if getattr(user, "is_authenticated", False) else None,
                    normalized_payload={
                        "preferred_name": resolution.preferred_name,
                        "email": resolution.email.lower(),
                        "organization_guess": "",
                        "relationship_context": "Historical recruiter correspondence",
                        "name_source": resolution.source,
                        "name_confidence": resolution.confidence,
                        "name_status": resolution.status,
                    },
                    provenance={
                        "source_grant_id": str(source_grant.id),
                        "name_resolution": {
                            "source": resolution.source,
                            "confidence": resolution.confidence,
                            "status": resolution.status,
                        },
                    },
                )
                provisional_created += 1

            ProvisionalDataMembership.objects.get_or_create(
                working_set=working_set,
                provisional_data=record,
                defaults={"position": position},
            )

        if evidence_created:
            imported += 1
        else:
            reused += 1

    _refresh_working_set_summary(working_set)
    return {
        "working_set_id": str(working_set.id),
        "imported": imported,
        "reused": reused,
        "provisional_created": provisional_created,
        "provisional_reused": provisional_reused,
    }


def import_latest_from_source_grant(
    source_grant: SourceGrant,
    *,
    user,
    adapter_key: str = "manual_v1",
    limit: int = 5,
    payload: dict | None = None,
) -> dict:
    """
    Fetch bounded messages through a provider adapter and import them under an
    ActionRun audit record.

    The manual adapter is the only V1 implementation today, but Gmail/IMAP/Drive
    readers should enter here after Switchboard has enforced the SourceGrant.
    """
    action_run = ActionRun.objects.create(
        initiative=source_grant.initiative,
        source_grant=source_grant,
        tool_name=f"source.{source_grant.connection.provider}.import_latest_{adapter_key}",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        service_name="switchboard",
        tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)),
        tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE)),
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk) if getattr(user, "is_authenticated", False) else "",
        request_payload={
            "source_grant_id": str(source_grant.id),
            "resource_kind": source_grant.resource_kind,
            "resource_id": source_grant.resource_id,
            "limit": limit,
            "adapter": adapter_key,
        },
    )
    try:
        adapter = get_source_provider_adapter(adapter_key)
        source_messages = adapter.fetch_latest_messages(source_grant, limit=limit, payload=payload)
        import_payloads = [message.as_import_payload() for message in source_messages]
        result = import_latest_messages(source_grant, import_payloads, user=user)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc), "adapter": adapter_key}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise

    result = {
        **result,
        "adapter": adapter_key,
        "messages_seen": len(source_messages),
        "action_run_id": str(action_run.id),
    }
    action_run.status = ActionRunStatus.SUCCEEDED
    action_run.result_payload = result
    action_run.completed_at = timezone.now()
    action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
    return result


def resolve_sender_name(message: dict) -> NameResolution:
    raw_header = str(message.get("from") or message.get("from_header") or message.get("sender_header") or "")
    display_name = str(message.get("sender_display_name") or "").strip()
    email = str(message.get("sender_email") or "").strip()

    parsed_name, parsed_email = parseaddr(raw_header)
    name = display_name or parsed_name
    email = email or parsed_email

    if _is_plausible_person_name(name):
        return NameResolution(
            preferred_name=_clean_name(name),
            email=email,
            source=NameSource.HEADER,
            confidence=NameConfidence.HIGH,
            status=NameStatus.READY,
        )

    signature = _extract_signature_name(str(message.get("body") or ""))
    if signature:
        return NameResolution(
            preferred_name=signature["name"],
            email=email,
            source=NameSource.SIGNATURE,
            confidence=NameConfidence.HIGH if signature["confidence"] == "high" else NameConfidence.MEDIUM,
            status=NameStatus.READY if signature["confidence"] == "high" else NameStatus.REVIEW_SUGGESTED,
            evidence_excerpt=signature["excerpt"],
        )

    return NameResolution(
        preferred_name=_clean_name(name),
        email=email,
        source=NameSource.UNKNOWN,
        confidence=NameConfidence.LOW,
        status=NameStatus.NEEDS_REVIEW,
    )


def verify_provisional_name(record: ProvisionalData, *, preferred_name: str, user, note: str = "") -> ProvisionalData:
    payload = dict(record.normalized_payload or {})
    payload["preferred_name"] = preferred_name.strip()
    payload["name_source"] = NameSource.HUMAN_VERIFIED
    payload["name_confidence"] = NameConfidence.HIGH
    payload["name_status"] = NameStatus.READY
    provenance = dict(record.provenance or {})
    provenance["verified_by"] = str(user.pk) if getattr(user, "is_authenticated", False) else None
    provenance["verified_at"] = timezone.now().isoformat()
    if note:
        provenance["verification_note"] = note
    record.normalized_payload = payload
    record.provenance = provenance
    record.save(update_fields=["normalized_payload", "provenance", "updated_at"])
    return record


def reject_provisional_data(record: ProvisionalData, *, user, working_set) -> None:
    """
    Mark a ProvisionalData record as rejected and remove it from the working set.
    The record is retained so the dedup pass can suppress the same email on re-import.
    """
    record.state = ProvisionalDataState.REJECTED
    provenance = dict(record.provenance or {})
    provenance["rejected_by"] = str(user.pk) if getattr(user, "is_authenticated", False) else None
    provenance["rejected_at"] = timezone.now().isoformat()
    record.provenance = provenance
    record.save(update_fields=["state", "provenance", "updated_at"])
    ProvisionalDataMembership.objects.filter(working_set=working_set, provisional_data=record).delete()
    _refresh_working_set_summary(working_set)


def _find_existing_recruiter_contact(group: Group, email: str) -> ProvisionalData | None:
    if not email:
        return None
    return ProvisionalData.objects.filter(
        group=group,
        kind="recruiter_contact",
        normalized_payload__email=email.lower(),
    ).first()


def _apply_name_resolution(record: ProvisionalData, resolution: NameResolution, *, user, update_existing: bool) -> None:
    payload = dict(record.normalized_payload or {})
    changed = False
    current_name_source = payload.get("name_source", NameSource.UNKNOWN)
    if update_existing and resolution.preferred_name and current_name_source != NameSource.HUMAN_VERIFIED:
        payload["preferred_name"] = resolution.preferred_name
        changed = True
    if resolution.email and not payload.get("email"):
        payload["email"] = resolution.email.lower()
        changed = True
    if current_name_source != NameSource.HUMAN_VERIFIED:
        payload["name_source"] = resolution.source
        payload["name_confidence"] = resolution.confidence
        payload["name_status"] = resolution.status
        changed = True
    if changed:
        record.normalized_payload = payload
        record.save(update_fields=["normalized_payload", "updated_at"])


def _message_fingerprint(source_grant: SourceGrant, message: dict) -> str:
    parts = [
        str(source_grant.id),
        str(message.get("provider_message_id") or message.get("id") or ""),
        str(message.get("from") or message.get("from_header") or message.get("sender_header") or ""),
        str(message.get("sender_email") or ""),
        str(message.get("sent_at") or message.get("date") or ""),
        str(message.get("subject") or ""),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _parse_sent_at(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    parsed = parse_datetime(str(value))
    if not parsed:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            parsed = None
    if parsed and timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _is_plausible_person_name(value: str) -> bool:
    name = _clean_name(value)
    if not name or "@" in name or len(name) < 3:
        return False
    lowered = re.sub(r"[^a-z ]", "", name.lower()).strip()
    if lowered in GENERIC_HEADER_NAMES:
        return False
    parts = [part for part in re.split(r"\s+", name) if part]
    if len(parts) < 2:
        return False
    if len(parts) > 5:
        return False
    return all(re.search(r"[A-Za-z]", part) for part in parts)


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value.strip("\"'<>")


def _extract_signature_name(body: str) -> dict | None:
    if not body:
        return None

    lines = [line.strip() for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    phrase_pattern = re.compile(rf"^({'|'.join(re.escape(p) for p in SIGNOFF_PHRASES)})[,!.\s-]*$", re.IGNORECASE)

    for idx, line in enumerate(lines):
        if not phrase_pattern.match(line):
            continue

        window = [candidate for candidate in lines[idx + 1 : idx + 5] if candidate]
        for candidate in window:
            cleaned = _clean_name(candidate)
            if _is_plausible_person_name(cleaned):
                excerpt_lines = [line] + window[:3]
                return {
                    "name": cleaned,
                    "confidence": "high",
                    "excerpt": "\n".join(excerpt_lines),
                }
            if _looks_like_single_name(cleaned):
                excerpt_lines = [line] + window[:3]
                return {
                    "name": cleaned,
                    "confidence": "medium",
                    "excerpt": "\n".join(excerpt_lines),
                }

    return None


def _looks_like_single_name(value: str) -> bool:
    name = _clean_name(value)
    if not name or "@" in name:
        return False
    if len(name.split()) != 1:
        return False
    return bool(re.match(r"^[A-Z][A-Za-z'-]{2,}$", name))


def push_working_set_to_lanternmail(
    working_set: WorkingSet,
    *,
    list_name: str,
    user,
) -> dict:
    """
    Create a named Listmonk list from the confirmed (name_status=ready) members
    of a Working Set and subscribe each one.

    DEV override: if SOURCEWORK_LANTERNMAIL_TEST_EMAILS is set in settings, that
    list of {email, name} dicts is used instead of the real verified members.
    Remove the setting before any real-recruiter push.
    """
    from lanternmail.services.listmonk_client import get_listmonk_client

    test_override = getattr(settings, "SOURCEWORK_LANTERNMAIL_TEST_EMAILS", None)

    if test_override:
        members_to_push = list(test_override)
    else:
        confirmed = (
            working_set.provisional_data_memberships
            .filter(provisional_data__normalized_payload__name_source=NameSource.HUMAN_VERIFIED)
            .select_related("provisional_data")
        )
        members_to_push = [
            {
                "email": m.provisional_data.normalized_payload.get("email", ""),
                "name": m.provisional_data.normalized_payload.get("preferred_name", ""),
            }
            for m in confirmed
            if m.provisional_data.normalized_payload.get("email")
        ]

    if not members_to_push:
        raise ValueError("No confirmed members with email addresses to push.")

    client = get_listmonk_client()
    lm_resp = client.create_list(
        name=list_name,
        list_type="private",
        optin="single",
        tags=["sourcework", "recruiter-pipeline"],
        description=f"Sourcework recruiter list — {working_set.title}",
    )
    list_id = lm_resp["data"]["id"]

    from lanternmail.services.exceptions import ListmonkBadRequestError

    results: list[dict] = []
    for member in members_to_push:
        try:
            sub_resp = client.create_subscriber(
                email=member["email"],
                name=member.get("name", ""),
                status="enabled",
                lists=[list_id],
                preconfirm_subscriptions=True,
            )
            results.append({
                "email": member["email"],
                "status": "subscribed",
                "subscriber_id": (sub_resp.get("data") or {}).get("id"),
            })
        except ListmonkBadRequestError:
            # Subscriber already exists — look them up and add to this list.
            try:
                search = client.search_subscribers(query=f"subscribers.email = '{member['email']}'")
                existing = ((search.get("data") or {}).get("results") or [None])[0]
                if existing and existing.get("id"):
                    client.update_subscriber_lists(existing["id"], add=[list_id], status="confirmed")
                    results.append({
                        "email": member["email"],
                        "status": "subscribed",
                        "subscriber_id": existing["id"],
                        "note": "existing subscriber added to list",
                    })
                else:
                    results.append({"email": member["email"], "status": "error", "detail": "Subscriber exists but could not be found by search."})
            except Exception as inner_exc:
                results.append({"email": member["email"], "status": "error", "detail": str(inner_exc)})
        except Exception as exc:
            results.append({"email": member["email"], "status": "error", "detail": str(exc)})

    return {
        "list_id": list_id,
        "list_name": list_name,
        "pushed": sum(1 for r in results if r["status"] == "subscribed"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
        "dev_override_active": bool(test_override),
    }


def _refresh_working_set_summary(working_set: WorkingSet) -> None:
    memberships = working_set.provisional_data_memberships.select_related("provisional_data")
    total = memberships.count()
    ready = 0
    needs_review = 0
    excluded = 0
    for membership in memberships:
        record = membership.provisional_data
        if record.state == ProvisionalDataState.REJECTED:
            excluded += 1
        elif record.normalized_payload.get("name_status") == NameStatus.READY:
            ready += 1
        else:
            needs_review += 1
    working_set.summary = {
        "total": total,
        "ready": ready,
        "needs_review": needs_review,
        "excluded": excluded,
    }
    working_set.save(update_fields=["summary", "updated_at"])
