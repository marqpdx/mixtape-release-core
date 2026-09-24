# folio/services/gate5_validate.py
#
# Gate 5 -- validation (prototype spec section 8). Deterministic only, no
# model. Rejects candidates that fail schema/grounding checks rather than
# silently trusting upstream gates -- this is the safety net for cases the
# grammar-constrained model calls should already prevent, not a
# replacement for them.

def _spans_overlap(a: dict, b: dict) -> bool:
    return a["source_span_start"] < b["source_span_end"] and b["source_span_start"] < a["source_span_end"]


def validate_candidates(raw_text: str, candidates: list[dict], gate1_output: dict) -> dict:
    """
    Returns {"valid_candidates": [...], "errors": [...], "warnings": [...]}.
    `valid_candidates` is the subset safe to persist as FolioMaterialCandidate
    rows (status=proposed) -- never confirmed here, per spec section 8
    ("no candidate can become confirmed structure automatically").
    """
    valid_candidates = []
    errors = []

    for candidate in candidates:
        start = candidate["source_span_start"]
        end = candidate["source_span_end"]
        source_text = candidate["source_text"]

        if start < 0 or end > len(raw_text) or start >= end:
            errors.append(f"{candidate['candidate_type']} span [{start}:{end}] is out of bounds")
            continue
        if raw_text[start:end] != source_text:
            errors.append(
                f"{candidate['candidate_type']} span [{start}:{end}] does not match raw_text at that offset"
            )
            continue
        valid_candidates.append(candidate)

    warnings = []

    material = [c for c in valid_candidates if c["candidate_type"] == "material"]
    material.sort(key=lambda c: c["source_span_start"])
    for prev, curr in zip(material, material[1:]):
        if _spans_overlap(prev, curr):
            warnings.append(
                f"material spans [{prev['source_span_start']}:{prev['source_span_end']}] and "
                f"[{curr['source_span_start']}:{curr['source_span_end']}] overlap"
            )

    count_cues = gate1_output.get("count_cues") or []
    if count_cues:
        expected = count_cues[0]["value"]
        actual = len(material)
        if expected != actual:
            warnings.append(
                f"count cue said {expected} ({count_cues[0]['text']!r}) but {actual} material "
                "candidate(s) were confirmed by Gate 3"
            )

    return {"valid_candidates": valid_candidates, "errors": errors, "warnings": warnings}
