"""The Dictionary provider for recognition (`folio.interpretation.recognition`).

Core calls `provide(author, folio)` and accepts exactly
`{"revision": int >= 0, "entries": [...]}`; anything else is refused as
`dictionary_unavailable`. So "no Dictionary here" is `None`, never an empty
Dictionary made up on the spot.

Storage is not built: the model design waits on the CTO
(`puddlejump/zz/_handoffs/handoff-2026-11-15-blue-folio-dictionary-provider.md`,
section 4). Until then `current_snapshot` finds nothing, and every reading
still refuses. When the model lands, only `current_snapshot` changes.
"""
import logging
from uuid import UUID

from folio.ownership import member_folios

logger = logging.getLogger(__name__)

_REQUIRED = {"entry_id", "revision", "shape_id", "shape_version", "names", "provenance"}
_ALLOWED = _REQUIRED | {"note"}


def current_snapshot(folio):
    """This Folio's confirmed Dictionary, or None when it has none.

    Returns `{"revision": int, "entries": [Contour shared.dictionary_entry
    0.1.0 values]}`, read for this one Folio only.
    """
    return None


def provide(author, folio):
    """Registered at app start (`folio.apps`). Read-only; creates nothing."""
    # Checked again here, though core has already authorized the Folio: the
    # Dictionary is the author's own, and a caller's mistake must not leak it.
    if not member_folios(author).filter(pk=folio.pk, deleted_at__isnull=True).exists():
        return None
    snapshot = current_snapshot(folio)
    if snapshot is None:
        return None
    if not _well_formed(snapshot):
        logger.error("folio_dictionary_snapshot_malformed folio=%s", folio.pk)
        return None
    # A stable order, so equal Dictionaries give equal context digests.
    return {"revision": snapshot["revision"],
            "entries": sorted(snapshot["entries"], key=lambda entry: entry["entry_id"])}


def _well_formed(snapshot):
    if (not isinstance(snapshot, dict) or set(snapshot) != {"revision", "entries"}
            or type(snapshot["revision"]) is not int or snapshot["revision"] < 0
            or not isinstance(snapshot["entries"], list)):
        return False
    seen = set()
    for entry in snapshot["entries"]:
        if not isinstance(entry, dict) or not _REQUIRED <= set(entry) <= _ALLOWED:
            return False
        names = entry["names"]
        if (not _uuid(entry["entry_id"]) or entry["entry_id"] in seen
                or type(entry["revision"]) is not int or entry["revision"] < 1
                or not isinstance(names, dict) or set(names) != {"main", "variants"}
                or not isinstance(names["variants"], list)
                or not all(isinstance(name, str) and name.strip() for name in [names["main"], *names["variants"]])):
            return False
        seen.add(entry["entry_id"])
    return True


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False
