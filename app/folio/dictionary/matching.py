"""Reference implementation of `folio_dictionary.nfc_casefold.v1`.

The rule is Contour's (`writing/strategies/fiction-note-recognition.md`,
"Folio Dictionary matching"): two values match when
NFC(casefold(NFC(a))) == NFC(casefold(NFC(b))). That is Unicode canonical
equivalence plus full case folding. It is not accent removal,
transliteration, fuzzy matching or locale tailoring (Turkish dotted and
dotless i stay distinct from plain i), and it never rewrites what is stored.

This is the one implementation. It uses the standard library only (no
Django, no database), so the eval harness can import it with `app/` on the
path: `from folio.dictionary import matching`. Do not copy it.

Offsets are Unicode code points into the original text, end exclusive, and
the quote is the exact original slice. A hit never covers part of a
normalization unit: "Stras" is not found in "Straße", nor "e" in a
decomposed "é".
"""
from __future__ import annotations

import hashlib
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

RULE = "folio_dictionary.nfc_casefold.v1"
UNICODE_VERSION = unicodedata.unidata_version


class AlignmentError(ValueError):
    """The text could not be aligned to its match key; no evidence is returned."""


def match_key(value: str) -> str:
    """The comparison key. Never store or display it."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).casefold())


def equivalent(a: str, b: str) -> bool:
    return match_key(a) == match_key(b)


@lru_cache(maxsize=1)
def identity() -> dict[str, str]:
    """Rule, implementation and Unicode data: pin all three beside any match."""
    source = Path(__file__).read_bytes()
    return {"rule": RULE, "implementation_sha256": hashlib.sha256(source).hexdigest(),
            "unicode_version": UNICODE_VERSION}


@lru_cache(maxsize=1)
def _trailing_starters() -> frozenset[str]:
    """Characters of combining class 0 that still compose with what precedes them.

    Derived from this interpreter's Unicode data, not a hand-kept list: the
    second half of every canonical pair, plus conjoining Hangul vowels and
    finals (composed by algorithm, so absent from the pair data).
    """
    found = {chr(cp) for cp in range(0x1161, 0x1176)} | {chr(cp) for cp in range(0x11A8, 0x11C3)}
    for cp in range(0x110000):
        pair = unicodedata.decomposition(chr(cp))
        if pair and not pair.startswith("<"):
            parts = pair.split()
            if len(parts) == 2:
                found.add(chr(int(parts[1], 16)))
    return frozenset(found)


def _starts_unit(ch: str) -> bool:
    if ch.isascii():
        return True
    # Decompose first: a few characters of class 0 (Tibetan U+0F73, U+0F75,
    # U+0F81) normalize into combining marks.
    first = unicodedata.normalize("NFD", ch)[0]
    return unicodedata.combining(first) == 0 and ch not in _trailing_starters()


def _align(text: str) -> tuple[str, dict[int, int], dict[int, int]]:
    """Return the text's key, with key offsets mapped back to original offsets.

    The text is cut into normalization units (a starter plus everything that
    can combine with it). `starts` maps the key offset where a unit begins to
    its original start; `ends` maps the key offset where a unit finishes to
    its original end. A key offset inside a unit is in neither.
    """
    cuts = [i for i, ch in enumerate(text) if i == 0 or _starts_unit(ch)] + [len(text)]
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    pieces = []
    offset = 0
    for begin, end in zip(cuts, cuts[1:]):
        piece = match_key(text[begin:end])
        starts[offset] = begin
        offset += len(piece)
        ends[offset] = end
        pieces.append(piece)
    key = "".join(pieces)
    if key != match_key(text):
        # Unit keys must concatenate to the whole key, or offsets would lie.
        raise AlignmentError("normalization units do not align with the match key")
    return key, starts, ends


def find_matches(text: str, entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every exact occurrence of every entry name in `text`.

    `entries` are Dictionary entry values (`entry_id`, `revision`,
    `names.main`, `names.variants`). One result per original span, ordered by
    position. When several entries match a span they are all listed as
    `alternatives`: never merged, never ranked. Main name and variants of one
    entry that hit the same span make one alternative, listing the stored
    spellings that matched, exactly as stored. Overlapping spans are all
    reported; this function prefers none.

    A match is a suggestion. It does not confirm the occurrence, and it
    carries no score.

    `word_bounded` is evidence, not part of the rule: false when the hit
    touches a letter, digit or underscore on either side ("Ann" in "Anna").
    The rule itself does not say whether such hits count.
    """
    key, starts, ends = _align(text)
    spans: dict[tuple[int, int], dict[tuple[str, int], list[str]]] = {}
    for entry in entries:
        names = entry["names"]
        entry_ref = (str(entry["entry_id"]), entry["revision"])
        for name in dict.fromkeys([names["main"], *names["variants"]]):
            if not isinstance(name, str) or not name:
                raise ValueError("a Dictionary name must be a non-empty string")
            needle = match_key(name)
            at = key.find(needle)
            while at != -1:
                if at in starts and at + len(needle) in ends:
                    span = (starts[at], ends[at + len(needle)])
                    spans.setdefault(span, {}).setdefault(entry_ref, []).append(name)
                at = key.find(needle, at + 1)
    return [{"start": start, "end": end, "quote": text[start:end], "rule": RULE,
             "word_bounded": not (_wordish(text, start - 1) or _wordish(text, end)),
             "alternatives": [{"entry_id": entry_id, "entry_revision": revision, "matched_names": matched}
                              for (entry_id, revision), matched in sorted(found.items())]}
            for (start, end), found in sorted(spans.items())]


def _wordish(text: str, index: int) -> bool:
    return 0 <= index < len(text) and (text[index].isalnum() or text[index] == "_")
