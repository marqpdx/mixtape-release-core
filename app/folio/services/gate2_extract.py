# folio/services/gate2_extract.py
#
# Gate 2 — subject/intention extraction (prototype spec §8-9). Small
# local-model task via Inkwell. The model returns verbatim text only —
# start/end offsets are computed deterministically here with str.find,
# never trusted from the model, because Tier 0 vetting
# (decisions/model-vetting/model-vetting-matrix.md, folio_gate2_subject_intention)
# showed model-reported offsets are not reliable even when the extracted
# text itself is coherent.

from inkwell.client import InkwellUnavailableError, service_generate

GATE2_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_found": {"type": "boolean"},
        "subject_text": {"type": "string"},
        "intention_found": {"type": "boolean"},
        "intention_text": {"type": "string"},
    },
    "required": ["subject_found", "subject_text", "intention_found", "intention_text"],
}

GATE2_SYSTEM = (
    "You are a materiality assessor inside a writing-craft tool. You extract; "
    "you do not rewrite. No inferred audience. No inferred thesis. No invented "
    "title if no defensible subject exists. It is valid to report not found. "
    "Every *_text value must be copied verbatim from the Text block only — "
    "never from these instructions or from the question below."
)


def _build_user_prompt(raw_text: str) -> str:
    return (
        "Text:\n" + raw_text + "\n\n"
        "Question (do not copy this question's own wording into your answer — "
        "it is only telling you what to look for in the Text above): what is "
        "the work principally about, and what does the writer say they intend "
        "to make or do? For each, report whether it was found and, if so, a "
        "short verbatim excerpt copied exactly from the Text."
    )


def _grounded_span(raw_text: str, found: bool, text: str) -> dict | None:
    """Locate `text` verbatim in raw_text. Ungrounded or empty text is
    treated as not found, per Gate 2's "extract; do not rewrite" rule and
    the spec's own "null is valid" allowance."""
    if not found:
        return None
    text = (text or "").strip()
    if not text:
        return None
    start = raw_text.find(text)
    if start == -1:
        return None
    return {"source_text": text, "start": start, "end": start + len(text)}


def extract_gate2(raw_text: str) -> dict:
    """
    Returns {"subject": span|None, "intention": span|None, "method": str}.
    Raises InkwellUnavailableError if the Inkwell service cannot be reached —
    callers decide how to degrade (Gate 1 output still stands on its own).
    """
    result = service_generate(
        system_prompt=GATE2_SYSTEM,
        prompt=_build_user_prompt(raw_text),
        schema=GATE2_SCHEMA,
        max_tokens=200,
        temperature=0.0,
    )
    parsed = result.get("result") or {}

    return {
        "subject": _grounded_span(
            raw_text, parsed.get("subject_found", False), parsed.get("subject_text", "")
        ),
        "intention": _grounded_span(
            raw_text, parsed.get("intention_found", False), parsed.get("intention_text", "")
        ),
        "method": result.get("method"),
    }
