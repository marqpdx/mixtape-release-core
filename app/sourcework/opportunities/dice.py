from __future__ import annotations

import re
from typing import Any

from .contracts import (
    OpportunityInterpretation,
    OpportunitySourceObservation,
    OpportunityValidation,
    OpportunityValidationStatus,
)
from .text import extract_email_addresses, html_to_readable_text


class DiceOpportunityAdapter:
    """Interpret already-acquired Dice observations without performing network access."""

    adapter_key = "dice_public_v1"
    adapter_version = "1.0"
    provider = "dice"
    source_shape_id = "employment.dice_listing"
    source_shape_version = "0.1"

    def interpret(self, observation: OpportunitySourceObservation) -> OpportunityInterpretation:
        if observation.provider != self.provider:
            return OpportunityInterpretation(
                normalized_payload={},
                validation=OpportunityValidation(
                    OpportunityValidationStatus.UNSUPPORTED,
                    (f"provider_mismatch:{observation.provider}",),
                ),
                confidence=0.0,
                source_shape_id=self.source_shape_id,
                source_shape_version=self.source_shape_version,
            )

        raw = observation.raw_payload
        listing_status = _clean(raw.get("listing_status"))
        if listing_status in {"dead", "expired", "gone", "410"}:
            return self._result(
                raw,
                observation,
                OpportunityValidationStatus.DEAD,
                ("detail_resource_not_live",),
                confidence=1.0,
            )

        title = str(raw.get("title") or "").strip()
        organization = str(raw.get("organization") or "").strip()
        if not title or not organization:
            missing = tuple(
                f"missing_required_field:{field_name}"
                for field_name, value in (("title", title), ("organization", organization))
                if not value
            )
            return self._result(
                raw,
                observation,
                OpportunityValidationStatus.DEGRADED,
                missing,
                confidence=0.55,
            )

        structured_arrangement = _clean(raw.get("arrangement"))
        prose = " ".join(
            str(value or "")
            for value in (raw.get("title"), raw.get("description"), observation.relevant_text)
        )
        prose_says_remote = bool(re.search(r"\bremote\b", prose, flags=re.IGNORECASE))
        structured_says_onsite = structured_arrangement in {"on-site", "onsite", "on site"}

        if prose_says_remote and structured_says_onsite:
            return self._result(
                raw,
                observation,
                OpportunityValidationStatus.CONTRADICTORY,
                ("remote_prose_conflicts_with_structured_onsite",),
                confidence=0.65,
            )

        reasons: tuple[str, ...] = ()
        status = OpportunityValidationStatus.VALID
        confidence = 0.95
        if not structured_arrangement:
            status = OpportunityValidationStatus.DEGRADED
            reasons = ("missing_structured_arrangement",)
            confidence = 0.78

        return self._result(raw, observation, status, reasons, confidence=confidence)

    def _result(
        self,
        raw: dict[str, Any],
        observation: OpportunitySourceObservation,
        status: OpportunityValidationStatus,
        reasons: tuple[str, ...],
        *,
        confidence: float,
    ) -> OpportunityInterpretation:
        raw_description = str(raw.get("description") or "").strip()
        description = html_to_readable_text(raw_description)
        listed_emails = extract_email_addresses(description)
        contact_email = str(raw.get("contact_email") or (listed_emails[0] if listed_emails else "")).strip()
        easy_apply = bool(raw.get("easyApply", raw.get("easy_apply", False)))
        application_url = str(raw.get("detailsPageUrl") or observation.canonical_url or "").strip()
        employer_type = str(raw.get("employerType") or raw.get("employer_type") or "").strip()
        recruiter_name = str(
            raw.get("recruiterName")
            or raw.get("recruiter_name")
            or raw.get("postedBy")
            or ""
        ).strip()
        application_method = (
            "recruiter_email"
            if contact_email
            else "dice_easy_apply"
            if easy_apply
            else "external_application"
        )
        normalized = {
            "source": self.provider,
            "source_id": observation.external_id,
            "source_url": observation.canonical_url,
            "title": str(raw.get("title") or "").strip(),
            "organization": str(raw.get("organization") or "").strip(),
            "staffing_organization": str(raw.get("staffing_organization") or "").strip(),
            "contact_email": contact_email,
            "contact_email_status": "unverified_from_listing" if contact_email else "not_found",
            "recruiter_name": recruiter_name,
            "employer_type": employer_type,
            "description": description,
            "arrangement": _clean(raw.get("arrangement")),
            "required_location": str(raw.get("required_location") or "").strip(),
            "engagement_type": _clean(raw.get("engagement_type")),
            "payment_form": _clean(raw.get("payment_form")),
            "duration": str(raw.get("duration") or "").strip(),
            "contract_to_hire": bool(raw.get("contract_to_hire", False)),
            "compensation_min": raw.get("compensation_min"),
            "compensation_max": raw.get("compensation_max"),
            "compensation_unit": _clean(raw.get("compensation_unit")),
            "currency": str(raw.get("currency") or "USD").upper(),
            "posted_at": raw.get("posted_at"),
            "updated_at": raw.get("updated_at"),
            "observed_at": (observation.observed_at or observation.retrieved_at).isoformat(),
            "last_verified_at": observation.retrieved_at.isoformat(),
            "skills": list(raw.get("skills") or []),
            "technologies": list(raw.get("technologies") or []),
            "domains": list(raw.get("domains") or []),
            "requirements": list(raw.get("requirements") or []),
            "application_method": application_method,
            "application_url": application_url,
            "easy_apply": easy_apply,
            "application_action": "outbound_email_available" if contact_email else "manual_application_required",
            "detail_acquired_at": raw.get("detail_acquired_at"),
            "validation_status": status.value,
            "validation_findings": list(reasons),
        }
        return OpportunityInterpretation(
            normalized_payload=normalized,
            validation=OpportunityValidation(status, reasons),
            confidence=confidence,
            source_shape_id=self.source_shape_id,
            source_shape_version=self.source_shape_version,
        )


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()
