"""How large a Dictionary may grow, checked where the writer can act.

A Folio's Dictionary rides in the recognition context, and a reading refuses
`context_too_large` past the wire profile's cap. That refusal comes at
reading time, for every reading in the Folio, long after the edit that
caused it. So a Dictionary edit is checked here first, against a smaller
budget derived from the same cap. The reading-time refusal stays as the
backstop; `test_dictionary_storage` holds the two together.
"""
from folio.interpretation import recognition_contract as wire
from heddle.errors import InterpretationError

# Room left for the rest of the context (title, bundle identity, digests).
# Measured 2026-11-15: 456 characters with no title, 1,994 with the worst
# title (255 control characters) and the largest revision. Doubled, so new
# context fields have room before the test that guards this fails.
CONTEXT_RESERVE = 4000
SNAPSHOT_BUDGET = wire.PROFILE["max_context_chars"] - CONTEXT_RESERVE


class DictionaryFull(InterpretationError):
    def __init__(self, size, budget=SNAPSHOT_BUDGET):
        super().__init__("dictionary_full", 413)
        self.size, self.budget = size, budget
        self.message = (f"This Folio's Dictionary is full: with this change its names would take {size:,} "
                        f"characters, and {budget:,} is the most a reading can carry. "
                        "Shorten or remove some names or variants, then try again.")


def slim(entry):
    """The wire projection of an entry: identity, Shape and names. Never the note."""
    return {"entry_id": str(entry.pk), "revision": entry.revision, "shape_id": entry.shape_id,
            "shape_version": entry.shape_version,
            "names": {"main": entry.main_name, "variants": list(entry.variants)}}


def projected_snapshot_size(revision, entries):
    """Characters the snapshot `{revision, entries}` takes in the context.

    `entries` are slim values. Counted with the reading's own serializer, so
    escapes cost here exactly what they cost there.
    """
    return len(wire.canonical({"revision": revision, "entries": list(entries)}).decode("utf-8"))


def check_budget(revision, entries):
    """Call from every Dictionary write, with the snapshot as it would be after it."""
    size = projected_snapshot_size(revision, entries)
    if size > SNAPSHOT_BUDGET:
        raise DictionaryFull(size)
    return size
