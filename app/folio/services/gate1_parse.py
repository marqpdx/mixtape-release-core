# folio/services/gate1_parse.py
#
# Gate 1 — deterministic surface parse (prototype spec §8). No LLM. Detects
# obvious structural signals and outputs a candidate span map, not final
# structure — Gate 3 (materiality classification) decides what's material.

import re

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_COUNT_CUE_NOUNS = r"(?:ideas?|thoughts?|things?|concerns?|items?|questions?|examples?|needs?|points?|reasons?)"

_ENUMERATION_RE = re.compile(
    r"(?:^|(?<=[\s;]))(?P<label>[a-zA-Z]|\d+)[\)\.]\s+"
)

_COUNT_CUE_RE = re.compile(
    r"\b(?P<number>\d+|" + "|".join(_NUMBER_WORDS.keys()) + r")\s+" + _COUNT_CUE_NOUNS,
    re.IGNORECASE,
)

_QUOTED_SPAN_RE = re.compile(
    '"([^"]+)"|“([^”]+)”'
)

_ABOUT_SUBJECT_RE = re.compile(
    r"\babout\s+(?P<subject>[A-Z][^.,;:\n]{0,80}?)(?=[.,;:\n]|$)"
)


def _count_value(text: str) -> int:
    if text.isdigit():
        return int(text)
    return _NUMBER_WORDS[text.lower()]


def parse_gate1(raw_text: str) -> dict:
    """
    Deterministic surface parse. Returns a candidate span map:
    enumerations, count_cues, quoted_spans, about_subject.
    """
    enumerations = []
    markers = list(_ENUMERATION_RE.finditer(raw_text))
    for i, match in enumerate(markers):
        label = match.group("label")
        item_start = match.start()
        next_start = markers[i + 1].start() if i + 1 < len(markers) else len(raw_text)
        item_text = raw_text[match.end():next_start].rstrip()
        item_text = re.sub(r"[;,]+$", "", item_text).rstrip()
        item_end = match.end() + len(item_text)
        if not item_text:
            continue
        enumerations.append({
            "label": label,
            "start": item_start,
            "end": item_end,
        })

    count_cues = []
    for match in _COUNT_CUE_RE.finditer(raw_text):
        count_cues.append({
            "value": _count_value(match.group("number")),
            "text": match.group(0),
            "start": match.start(),
            "end": match.end(),
        })

    quoted_spans = []
    for match in _QUOTED_SPAN_RE.finditer(raw_text):
        quoted_spans.append({
            "text": match.group(1) or match.group(2),
            "start": match.start(),
            "end": match.end(),
        })

    about_match = _ABOUT_SUBJECT_RE.search(raw_text)
    about_subject = None
    if about_match:
        about_subject = {
            "source_text": about_match.group("subject").strip(),
            "start": about_match.start("subject"),
            "end": about_match.end("subject"),
        }

    return {
        "enumerations": enumerations,
        "count_cues": count_cues,
        "quoted_spans": quoted_spans,
        "about_subject": about_subject,
    }
