"""The Dictionary provider for recognition (`folio.interpretation.recognition`).

Core calls `provide(author, folio)` and accepts exactly
`{"revision": int >= 0, "entries": [...]}`; anything else is refused as
`dictionary_unavailable`. So "no Dictionary here" is `None`, never an empty
Dictionary made up on the spot. A Dictionary exists once
`folio.dictionary.commands.open_dictionary` has opened it.

Entries are served slim (`folio.dictionary.budget.slim`): identity, Shape
and names. The writer's note and the provenance stay in core; nothing that
reads the context uses them, and a note is private free text.
"""
import logging
from uuid import UUID

from folio.dictionary.budget import slim
from folio.models import Folio, FolioDictionaryEntry
from folio.ownership import member_folios

logger = logging.getLogger(__name__)

_KEYS = {"entry_id", "revision", "shape_id", "shape_version", "names"}


def _revision(folio):
    return Folio.objects.filter(pk=folio.pk).values_list("dictionary_revision", flat=True).first()


def current_snapshot(folio):
    """This Folio's Dictionary as stored now, or None when it has none.

    Read-only, this Folio only, active entries only. Every write changes the
    revision in its own transaction, so the same revision read before and
    after the entries means the entries belong to it.
    """
    for _ in range(3):
        revision = _revision(folio)
        if revision is None:
            return None
        entries = [slim(entry) for entry in FolioDictionaryEntry.objects.filter(
            folio_id=folio.pk, state="active", deleted_at__isnull=True)]
        if _revision(folio) == revision:
            return {"revision": revision, "entries": entries}
    logger.error("folio_dictionary_snapshot_unsettled folio=%s", folio.pk)
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
        if not isinstance(entry, dict) or set(entry) != _KEYS:
            return False
        names = entry["names"]
        if (not _uuid(entry["entry_id"]) or entry["entry_id"] in seen
                or type(entry["revision"]) is not int or entry["revision"] < 1
                or not isinstance(names, dict) or set(names) != {"main", "variants"}
                or not all(isinstance(entry[key], str) and entry[key].strip() for key in ("shape_id", "shape_version"))
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
