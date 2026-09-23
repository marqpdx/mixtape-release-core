from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from sourcework.models import (
    ExternalConnection,
    ExternalConnectionStatus,
    ProvisionalData,
    ProvisionalDataMembership,
    ProvisionalDataState,
    SourceEvidence,
    SourceGrant,
    SourceGrantStatus,
    WorkingSet,
    WorkingSetStatus,
)

from .contracts import (
    OpportunitySearchProfile,
    OpportunitySourceAdapter,
    OpportunitySourceObservation,
    OpportunityValidationStatus,
)


PUBLIC_OPPORTUNITY_RESOURCE_KIND = "public_search"
PUBLIC_OPPORTUNITY_RESOURCE_ID = "opportunities"
PUBLIC_OPPORTUNITY_CAPABILITIES = ["search", "read_detail"]


@dataclass(frozen=True)
class OpportunityIngestResult:
    working_set_id: str
    observations_seen: int
    evidence_created: int
    provisional_created: int
    provisional_updated: int
    rejected_before_materialization: int


@transaction.atomic
def provision_public_opportunity_source(*, group, initiative, user, provider: str = "dice") -> SourceGrant:
    """Create the credentialless connection/grant boundary for a public source."""

    connection, _ = ExternalConnection.objects.update_or_create(
        group=group,
        provider=provider,
        provider_account_id="public",
        defaults={
            "owner": None,
            "display_name": f"{provider.title()} Public Search",
            "credential_reference": "",
            "credential_payload": "",
            "provider_scopes": [],
            "status": ExternalConnectionStatus.READY,
            "connected_at": timezone.now(),
            "metadata": {"access_mode": "public", "credentials_required": False},
        },
    )
    grant, _ = SourceGrant.objects.update_or_create(
        connection=connection,
        resource_kind=PUBLIC_OPPORTUNITY_RESOURCE_KIND,
        resource_id=PUBLIC_OPPORTUNITY_RESOURCE_ID,
        initiative=initiative,
        defaults={
            "display_name": f"{provider.title()} Opportunity Search",
            "capabilities": PUBLIC_OPPORTUNITY_CAPABILITIES,
            "status": SourceGrantStatus.ACTIVE,
            "created_by": user,
            "revoked_at": None,
            "metadata": {"access_mode": "public", "submission_allowed": False},
        },
    )
    return grant


@transaction.atomic
def provision_member_public_opportunity_source(*, user, initiative=None, provider: str = "dice") -> SourceGrant:
    """Create a credentialless public-source boundary sponsored by one member."""

    connection, _ = ExternalConnection.objects.update_or_create(
        group=None,
        owner=user,
        provider=provider,
        provider_account_id="public",
        defaults={
            "display_name": f"{provider.title()} Public Search",
            "credential_reference": "",
            "credential_payload": "",
            "provider_scopes": [],
            "status": ExternalConnectionStatus.READY,
            "connected_at": timezone.now(),
            "metadata": {"access_mode": "public", "credentials_required": False},
        },
    )
    grant, _ = SourceGrant.objects.update_or_create(
        connection=connection,
        resource_kind=PUBLIC_OPPORTUNITY_RESOURCE_KIND,
        resource_id=PUBLIC_OPPORTUNITY_RESOURCE_ID,
        initiative=initiative,
        defaults={
            "display_name": f"{provider.title()} Opportunity Search",
            "capabilities": PUBLIC_OPPORTUNITY_CAPABILITIES,
            "status": SourceGrantStatus.ACTIVE,
            "created_by": user,
            "revoked_at": None,
            "metadata": {"access_mode": "public", "submission_allowed": False},
        },
    )
    return grant


@transaction.atomic
def ingest_opportunity_observations(
    *,
    source_grant: SourceGrant,
    search_profile: OpportunitySearchProfile,
    observations: Iterable[OpportunitySourceObservation],
    adapter: OpportunitySourceAdapter,
    user,
    title: str | None = None,
) -> OpportunityIngestResult:
    _validate_public_grant(source_grant, adapter)

    observations = list(observations)
    working_set = WorkingSet.objects.create(
        group=source_grant.connection.group,
        owner_user=user if source_grant.connection.group_id is None else None,
        initiative=source_grant.initiative,
        title=title or f"{adapter.provider.title()} Opportunity Search",
        purpose="Review externally observed opportunities before consequential action.",
        status=WorkingSetStatus.ACTIVE,
        source=adapter.provider,
        search_brief=search_profile.as_dict(),
        execution_metadata={
            "adapter": adapter.adapter_key,
            "adapter_version": adapter.adapter_version,
            "source_grant_id": str(source_grant.id),
            "started_at": timezone.now().isoformat(),
        },
        created_by=user,
    )

    evidence_created = 0
    provisional_created = 0
    provisional_updated = 0
    rejected = 0

    for position, observation in enumerate(observations):
        interpretation = adapter.interpret(observation)
        normalized_payload = _with_preliminary_fit(
            interpretation.normalized_payload,
            search_profile,
        )
        evidence, was_evidence_created = SourceEvidence.objects.update_or_create(
            source_grant=source_grant,
            provider_message_id=observation.external_id,
            defaults={
                "provider": observation.provider,
                "sent_at": observation.observed_at,
                "subject": str(observation.raw_payload.get("title") or ""),
                "source_fingerprint": _source_fingerprint(observation),
                "body_snapshot_status": "bounded_excerpt",
                "bounded_excerpt": observation.relevant_text[:4000],
                "metadata": {
                    "canonical_url": observation.canonical_url,
                    "retrieved_at": observation.retrieved_at.isoformat(),
                    "validation": interpretation.validation.as_dict(),
                    "source_shape_id": interpretation.source_shape_id,
                    "source_shape_version": interpretation.source_shape_version,
                    "raw_metadata": observation.raw_payload,
                },
            },
        )
        evidence_created += int(was_evidence_created)

        if interpretation.validation.status in {
            OpportunityValidationStatus.DEAD,
            OpportunityValidationStatus.UNSUPPORTED,
        }:
            rejected += 1
            continue

        record_query = ProvisionalData.objects.filter(
            group=source_grant.connection.group,
            kind="opportunity_candidate",
            source_type=adapter.provider,
            source_external_id=observation.external_id,
        )
        if source_grant.connection.group_id is None:
            record_query = record_query.filter(owner_user=user)
        record = record_query.first()
        created = record is None
        if created:
            record = ProvisionalData(
                group=source_grant.connection.group,
                kind="opportunity_candidate",
                source_type=adapter.provider,
                source_external_id=observation.external_id,
                state=ProvisionalDataState.NEW,
                owner_user=user,
            )

        record.source_locator = observation.canonical_url
        record.captured_at = timezone.now()
        record.observed_at = observation.observed_at or observation.retrieved_at
        record.raw_payload = observation.raw_payload
        record.normalized_payload = normalized_payload
        record.confidence = interpretation.confidence
        record.provenance = {
            "source_grant_id": str(source_grant.id),
            "adapter": adapter.adapter_key,
            "adapter_version": adapter.adapter_version,
            "source_shape_id": interpretation.source_shape_id,
            "source_shape_version": interpretation.source_shape_version,
            "validation": interpretation.validation.as_dict(),
        }
        record.source_evidence = evidence
        record.save()

        if created:
            provisional_created += 1
        else:
            provisional_updated += 1

        ProvisionalDataMembership.objects.get_or_create(
            working_set=working_set,
            provisional_data=record,
            defaults={"position": position},
        )

    materialized = provisional_created + provisional_updated
    working_set.summary = {
        "observations_seen": len(observations),
        "materialized": materialized,
        "rejected_before_materialization": rejected,
    }
    working_set.execution_metadata = {
        **working_set.execution_metadata,
        "completed_at": timezone.now().isoformat(),
        **working_set.summary,
    }
    working_set.save(update_fields=["summary", "execution_metadata", "updated_at"])

    return OpportunityIngestResult(
        working_set_id=str(working_set.id),
        observations_seen=len(observations),
        evidence_created=evidence_created,
        provisional_created=provisional_created,
        provisional_updated=provisional_updated,
        rejected_before_materialization=rejected,
    )


def _validate_public_grant(source_grant: SourceGrant, adapter: OpportunitySourceAdapter) -> None:
    if source_grant.status != SourceGrantStatus.ACTIVE:
        raise ValueError("SourceGrant must be active.")
    if source_grant.resource_kind != PUBLIC_OPPORTUNITY_RESOURCE_KIND:
        raise ValueError("SourceGrant does not authorize public opportunity search.")
    if source_grant.connection.provider != adapter.provider:
        raise ValueError("SourceGrant provider does not match the opportunity adapter.")
    if source_grant.connection.credential_payload:
        raise ValueError("Public opportunity search must not use stored credentials.")
    missing = set(PUBLIC_OPPORTUNITY_CAPABILITIES) - set(source_grant.capabilities)
    if missing:
        raise ValueError(f"SourceGrant is missing capabilities: {', '.join(sorted(missing))}")


def _source_fingerprint(observation: OpportunitySourceObservation) -> str:
    import hashlib

    value = f"{observation.provider}|{observation.external_id}|{observation.canonical_url}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _with_preliminary_fit(payload: dict, search_profile: OpportunitySearchProfile) -> dict:
    """Attach transparent lexical signals without pretending to be a full fit judgment."""

    text = " ".join(
        str(payload.get(field) or "")
        for field in ("title", "description", "organization", "arrangement", "engagement_type")
    ).lower()
    positive_terms = tuple(
        dict.fromkeys(
            term.strip()
            for term in (
                *search_profile.seniority,
                *search_profile.strong_domains,
                *search_profile.strong_technologies,
            )
            if term.strip()
        )
    )
    matched = [term for term in positive_terms if term.lower() in text]
    concerns = [term for term in search_profile.exclusions if term.strip() and term.lower() in text]
    label = "caution" if concerns else "promising" if len(matched) >= 2 else "review"
    return {
        **payload,
        "preliminary_fit": {
            "label": label,
            "matched_terms": matched,
            "concerns": concerns,
            "method": "transparent_lexical_v1",
        },
    }
