import hashlib
import re
from dataclasses import dataclass
from email.utils import parseaddr

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
    ProvisionalThing,
    ProvisionalThingStatus,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
    WorkingSetMembership,
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
    provisional person records. The caller is responsible for ensuring the
    messages came through the SourceGrant/Switchboard boundary.
    """
    group = source_grant.connection.group
    working_set = default_recruiter_working_set(group, user, source_grant.initiative)

    imported = 0
    reused = 0
    provisional_created = 0
    provisional_reused = 0

    for position, message in enumerate(messages[:5]):
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

            thing = _find_existing_person(group, resolution.email)
            if thing:
                provisional_reused += 1
                _apply_name_resolution(thing, resolution, user=user, update_existing=True)
            else:
                thing = ProvisionalThing.objects.create(
                    group=group,
                    possible_type="person",
                    status=(
                        ProvisionalThingStatus.READY
                        if resolution.status == NameStatus.READY
                        else ProvisionalThingStatus.PROVISIONAL
                    ),
                    preferred_name=resolution.preferred_name,
                    email=resolution.email,
                    name_source=resolution.source,
                    name_confidence=resolution.confidence,
                    name_status=resolution.status,
                    payload={"relationship_context": "Historical recruiter correspondence"},
                    created_by=user if getattr(user, "is_authenticated", False) else None,
                )
                provisional_created += 1

            thing.evidence.add(evidence)
            WorkingSetMembership.objects.get_or_create(
                working_set=working_set,
                provisional_thing=thing,
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


def verify_provisional_name(thing: ProvisionalThing, *, preferred_name: str, user, note: str = "") -> ProvisionalThing:
    thing.preferred_name = preferred_name.strip()
    thing.name_source = NameSource.HUMAN_VERIFIED
    thing.name_confidence = NameConfidence.HIGH
    thing.name_status = NameStatus.READY
    thing.status = ProvisionalThingStatus.READY
    thing.verified_by = user if getattr(user, "is_authenticated", False) else None
    thing.verified_at = timezone.now()
    payload = thing.payload or {}
    if note:
        payload["verification_note"] = note
    thing.payload = payload
    thing.save(
        update_fields=[
            "preferred_name",
            "name_source",
            "name_confidence",
            "name_status",
            "status",
            "verified_by",
            "verified_at",
            "payload",
            "updated_at",
        ]
    )
    return thing


def _find_existing_person(group: Group, email: str) -> ProvisionalThing | None:
    if not email:
        return None
    return ProvisionalThing.objects.filter(group=group, possible_type="person", email__iexact=email).first()


def _apply_name_resolution(thing: ProvisionalThing, resolution: NameResolution, *, user, update_existing: bool) -> None:
    changed = []
    if update_existing and resolution.preferred_name and thing.name_source != NameSource.HUMAN_VERIFIED:
        thing.preferred_name = resolution.preferred_name
        changed.append("preferred_name")
    if resolution.email and not thing.email:
        thing.email = resolution.email
        changed.append("email")
    if thing.name_source != NameSource.HUMAN_VERIFIED:
        thing.name_source = resolution.source
        thing.name_confidence = resolution.confidence
        thing.name_status = resolution.status
        changed.extend(["name_source", "name_confidence", "name_status"])
    if resolution.status == NameStatus.READY and thing.status == ProvisionalThingStatus.PROVISIONAL:
        thing.status = ProvisionalThingStatus.READY
        changed.append("status")
    if changed:
        changed.append("updated_at")
        thing.save(update_fields=sorted(set(changed)))


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


def _refresh_working_set_summary(working_set: WorkingSet) -> None:
    memberships = working_set.memberships.select_related("provisional_thing")
    total = memberships.count()
    ready = 0
    needs_review = 0
    excluded = 0
    for membership in memberships:
        thing = membership.provisional_thing
        if thing.status == ProvisionalThingStatus.EXCLUDED:
            excluded += 1
        elif thing.name_status == NameStatus.READY:
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
