# fundamentals/services/name_matching.py
#
# Name normalising and near-duplicate matching — Shuttle ADR-0058, SH-1.
#
# One service for Places, things (CommonsItem) and Ideas (Tag, once SH-3
# marks them), and later Storyboard Entity matching. Deliberately
# domain-agnostic: callers supply the (object, name) candidates to compare
# against — how that scope is built (per-Location for Place, per-sponsor
# for CommonsItem, etc.) is each consumer's own business logic, not this
# service's. Extends the idea in storyboard.services.match_entity_alias
# (exact, case-folded) rather than forking it: this adds fuzzy near-
# duplicate detection on top of the same two outcomes (a confident match,
# or nothing confident enough to act on silently).
#
# Two-tier normalisation, not one, because "exact" and "near-duplicate"
# need to mean different things. A *light* normalisation (case-fold,
# collapse whitespace, strip accents — punctuation left alone) decides
# whether something is a clear, silent match: the same name re-entered.
# A *full* normalisation (light, plus stripping punctuation) feeds the
# fuzzy score: "Choir Choir Choir" against "Choir! Choir! Choir!" are
# identical once punctuation is gone, but they are NOT the same string
# light-normalised, so they are a near-duplicate pair raised once for a
# person to confirm — not silently merged. A single-tier scheme that
# strips punctuation before the exact check would wrongly call that pair
# an exact match.
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from rapidfuzz import fuzz

NEAR_DUPLICATE_THRESHOLD = 90  # RapidFuzz score (0-100) on the fully-normalised forms


class MatchState(str, Enum):
    FOUND = "found"
    NEAR_DUPLICATE = "near_duplicate"
    NEW = "new"


@dataclass
class MatchCandidate:
    object: Any
    name: str
    score: float  # 0-100; 100 for an exact-but-not-light-exact match


@dataclass
class MatchResult:
    state: MatchState
    exact: Any | None = None  # the object, when state is FOUND
    candidates: list[MatchCandidate] = field(default_factory=list)  # when state is NEAR_DUPLICATE


def normalize_light(raw: str) -> str:
    """Case-fold, strip accents, collapse whitespace. Punctuation is kept."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def normalize_full(raw: str) -> str:
    """normalize_light, plus stripping punctuation. Used only for fuzzy scoring."""
    text = normalize_light(raw)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def match_name(
    *,
    name: str,
    candidates: Iterable[tuple[Any, str]],
    near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> MatchResult:
    """
    Given a name and existing (object, name) candidates, return:
    - FOUND, with `exact` set — a clear match, safe to use silently;
    - NEAR_DUPLICATE, with `candidates` — raised once for a person to confirm;
    - NEW — nothing close enough to act on.

    An exact-but-ambiguous match (more than one light-exact candidate, or a
    light-exact candidate alongside another near-duplicate) is surfaced as
    NEAR_DUPLICATE rather than silently picked — unlike
    storyboard.services.match_entity_alias, which returns None on ambiguity.
    This service feeds a packet for human review, not an unattended write,
    so ambiguity should be shown, not swallowed.
    """
    full_needle = normalize_full(name)
    if not full_needle:
        return MatchResult(state=MatchState.NEW)
    light_needle = normalize_light(name)

    exact: list[MatchCandidate] = []
    near: list[MatchCandidate] = []
    for obj, candidate_name in candidates:
        full_candidate = normalize_full(candidate_name)
        if not full_candidate:
            continue
        if normalize_light(candidate_name) == light_needle:
            exact.append(MatchCandidate(object=obj, name=candidate_name, score=100.0))
            continue
        score = fuzz.WRatio(full_needle, full_candidate)
        if score >= near_duplicate_threshold:
            near.append(MatchCandidate(object=obj, name=candidate_name, score=score))

    if len(exact) == 1 and not near:
        return MatchResult(state=MatchState.FOUND, exact=exact[0].object)

    pooled = exact + near
    if pooled:
        pooled.sort(key=lambda c: c.score, reverse=True)
        return MatchResult(state=MatchState.NEAR_DUPLICATE, candidates=pooled)

    return MatchResult(state=MatchState.NEW)


def match_against_queryset(
    *,
    name: str,
    queryset,
    name_field: str = "name",
    near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> MatchResult:
    """Convenience wrapper: build candidates from a queryset already scoped by the caller."""
    candidates = ((obj, getattr(obj, name_field)) for obj in queryset)
    return match_name(
        name=name, candidates=candidates, near_duplicate_threshold=near_duplicate_threshold,
    )
