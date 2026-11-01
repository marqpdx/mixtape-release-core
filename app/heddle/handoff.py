"""HD-8 (ADR-0061, Headnote 2026-11-01): the hand-off. A kept Sighting
becomes a `ProvisionalData` record, built under the Provisional Data ADR
(PD-5) and supervised here. Heddle's remit ends at this function (the
boundary, same Headnote): once the record exists, the provisional layer
(`decisions/provisional-data-adr/`) owns what happens to it next.

Dismissing a Sighting needs no code here — it simply fades, as Heddle
already does (D5): a surface that doesn't call `keep_sighting` for a
given Sighting has, by construction, let it go.

Shape and meaning checks for a Sighting's *contents* already happened
upstream, in the surface's own `Reading.validate_findings` (D7) before
the Sighting ever reached a person to keep. There is no generic Contour
schema registry a hand-off function could re-validate against today
(D9) — the one check made here, that the Shape's own fields survived
into the kept Sighting at all, is what's available without one; it is
not a substitute for real Shape validation, and that gap is named
rather than quietly papered over (build brief F2).
"""
from __future__ import annotations

from django.db import transaction

from sourcework.models import ProvisionalData, ProvisionalDataState

from .errors import InterpretationError

# The D8 envelope: fields every Sighting carries regardless of Shape.
# Everything else on the dict is the Shape's own fields.
_ENVELOPE_FIELDS = frozenset({"sighting_id", "shape_id", "shape_version", "confidence",
                              "source_locator", "uncertain"})

_CONFIDENCE_SCORES = {"high": 1.0, "medium": 0.6, "low": 0.3}


def _confidence_score(value):
    if isinstance(value, (int, float)):
        return float(value)
    return _CONFIDENCE_SCORES.get(value)


@transaction.atomic
def keep_sighting(*, sighting: dict, action_run, group=None, owner_user=None) -> ProvisionalData:
    """Build brief §3: the person's keep is the trigger. One transaction.

    `action_run` is the Heddle reading (the weave's parent ActionRun) the
    Sighting came from — provenance points back to it, not to a child
    execution, since a Sighting has no identity independent of its
    reading. `group`/`owner_user` is the sponsor the calling surface
    passes; no fallback (F3's caller decides which it has).
    """
    if not group and not owner_user:
        raise InterpretationError("sponsor_required", 400)

    shape_fields = {key: value for key, value in sighting.items() if key not in _ENVELOPE_FIELDS}
    if not shape_fields:
        # F2 (recommended): reject outright rather than keep a record
        # that carries none of its Shape's own fields. The caller is
        # expected to surface "shape_fields_missing" to the person.
        raise InterpretationError("shape_fields_missing", 422)

    return ProvisionalData.objects.create(
        group=group,
        owner_user=owner_user,
        kind=sighting["shape_id"],
        shape_id=sighting["shape_id"],
        shape_version=sighting["shape_version"],
        source_type="heddle",
        source_locator=str(sighting.get("source_locator") or ""),
        state=ProvisionalDataState.NEW,
        confidence=_confidence_score(sighting.get("confidence")),
        # Kept verbatim so a later, better Shape can re-extract (spike
        # `zz/spike-emergent-data-types.md`, "raw capture beside structure").
        raw_payload=sighting,
        normalized_payload=shape_fields,
        provenance={
            "kind": "heddle_sighting",
            "weave_action_run_id": str(action_run.pk),
            "sighting_id": sighting["sighting_id"],
            "shape_id": sighting["shape_id"],
            "shape_version": sighting["shape_version"],
            "uncertain": sighting.get("uncertain") or [],
        },
    )
