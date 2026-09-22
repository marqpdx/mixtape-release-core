from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class OpportunityValidationStatus(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    CONTRADICTORY = "contradictory"
    DEAD = "dead"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class OpportunitySearchProfile:
    """Versioned search intent captured with every opportunity Working Set."""

    profile_id: str
    version: str
    geography: tuple[str, ...] = ()
    engagement_types: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ()
    strong_domains: tuple[str, ...] = ()
    strong_technologies: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    freshness_hours: int = 72
    overrides: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpportunitySourceObservation:
    """Provider-neutral acquisition result retained before interpretation."""

    provider: str
    external_id: str
    canonical_url: str
    retrieved_at: datetime
    raw_payload: dict[str, Any]
    observed_at: datetime | None = None
    relevant_text: str = ""


@dataclass(frozen=True)
class OpportunityValidation:
    status: OpportunityValidationStatus
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class OpportunityInterpretation:
    normalized_payload: dict[str, Any]
    validation: OpportunityValidation
    confidence: float
    source_shape_id: str
    source_shape_version: str


class OpportunitySourceAdapter(Protocol):
    adapter_key: str
    adapter_version: str
    provider: str

    def interpret(self, observation: OpportunitySourceObservation) -> OpportunityInterpretation:
        ...
