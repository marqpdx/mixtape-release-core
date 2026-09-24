# folio/services/gate4_normalize.py
#
# Gate 4 -- minimal display normalization (prototype spec section 8).
# Deterministic only, no model. Takes Gate 1-3 output and produces
# candidate dicts ready for Gate 5 validation and persistence as
# FolioMaterialCandidate rows. Only material:true Gate 3 items become
# material candidates -- non-material findings stay in debug output only,
# per "the writer decides whether Hildegard found the right things"
# (spec section 8, Human inspection checkpoint C).

import re

# Strips a leading enumeration marker ("a)", "3.", etc.) so display_text
# shows the item's own words, while the label itself is kept separately
# on the candidate record.
_LEADING_LABEL_RE = re.compile(r"^\s*(?:[a-zA-Z]|\d+)[\)\.]\s*")

_REPEATED_SPACE_RE = re.compile(r"[ \t]{2,}")


def _clean_display_text(source_text: str, strip_label: bool) -> str:
    text = source_text
    if strip_label:
        text = _LEADING_LABEL_RE.sub("", text, count=1)
    text = text.strip()
    text = _REPEATED_SPACE_RE.sub(" ", text)
    return text


def build_candidates(raw_text: str, gate2_output: dict | None, gate3_output: dict | None) -> list[dict]:
    """
    Returns a list of candidate dicts (not yet validated or persisted):
    {candidate_type, ordinal, source_span_start, source_span_end,
    source_text, display_text, reason_code}.
    """
    candidates: list[dict] = []

    if gate2_output:
        subject = gate2_output.get("subject")
        if subject:
            candidates.append({
                "candidate_type": "subject",
                "ordinal": None,
                "source_span_start": subject["start"],
                "source_span_end": subject["end"],
                "source_text": subject["source_text"],
                "display_text": _clean_display_text(subject["source_text"], strip_label=False),
                "reason_code": "",
            })
        intention = gate2_output.get("intention")
        if intention:
            candidates.append({
                "candidate_type": "intention",
                "ordinal": None,
                "source_span_start": intention["start"],
                "source_span_end": intention["end"],
                "source_text": intention["source_text"],
                "display_text": _clean_display_text(intention["source_text"], strip_label=False),
                "reason_code": "",
            })

    if gate3_output:
        material_items = [item for item in gate3_output.get("items", []) if item.get("material")]
        # Ordinal follows source order, not model output order.
        material_items.sort(key=lambda item: item["source_start"])
        for ordinal, item in enumerate(material_items, start=1):
            source_text = raw_text[item["source_start"]:item["source_end"]]
            candidates.append({
                "candidate_type": "material",
                "ordinal": ordinal,
                "source_span_start": item["source_start"],
                "source_span_end": item["source_end"],
                "source_text": source_text,
                "display_text": _clean_display_text(source_text, strip_label=True),
                "reason_code": item.get("reason_code", ""),
            })

    return candidates


def derive_title(candidates: list[dict]) -> str | None:
    """
    Near-verbatim short form only, per spec section 8 -- the subject
    candidate's own display text, never generated or paraphrased. Returns
    None when no subject was found, so callers can leave an existing
    title untouched.
    """
    for candidate in candidates:
        if candidate["candidate_type"] == "subject" and candidate["display_text"]:
            return candidate["display_text"]
    return None
