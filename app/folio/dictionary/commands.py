"""Dictionary write paths: open, add, edit, remove, and remember (from a decision).

Every change, in one transaction: lock the Folio, then the entries it touches
in id order; check the writer's expected revisions; check the size budget
against the snapshot as it would be after; write the entry, a write-once
revision and a write-once receipt; add one to `dictionary_revision` and to
`context_revision`. No change re-reads a note.

Merge is refused (`merge_not_supported`) until its semantics are settled
(CTO, 2026-11-16). The author of the Folio is the only writer.
"""
from datetime import timezone as tz

from django.db import transaction
from django.utils import timezone

from folio.dictionary.budget import check_budget, slim
from folio.models import FolioDictionaryEntry, FolioDictionaryEntryRevision, FolioDictionaryOperation
from folio.services.interpretation import owned_folio
from heddle.bundle import digest
from heddle.errors import InterpretationError
from storyboard.models import Entity

# The Shapes a Folio's type lets its Dictionary hold, with the version an
# entry records. Fiction is the only type with a Dictionary today.
ALLOWED_SHAPES = {"fiction": {"writing.character": "0.2.0", "writing.setting": "0.2.0"}}
ENTITY_KIND = {"writing.character": "character", "writing.setting": "setting"}
MAX_NAME, MAX_VARIANTS, MAX_NOTE = 255, 32, 2000


@transaction.atomic
def open_dictionary(*, author, folio_id):
    """Give the author's Folio an empty Dictionary. Safe to repeat.

    Deliberate and owner-authorized: the provider never opens one, so a
    Folio without a Dictionary keeps refusing readings until this runs.
    """
    folio = owned_folio(author, folio_id, lock=True)
    opened = folio.dictionary_revision is None
    if opened:
        folio.dictionary_revision = 0
        folio.context_revision += 1  # the context now carries a Dictionary
        folio.save(update_fields=["dictionary_revision", "context_revision", "updated_at"])
    return {"folio_id": str(folio.pk), "opened": opened, "dictionary_revision": folio.dictionary_revision,
            "context_revision": folio.context_revision}


# Reading -------------------------------------------------------------------

def entry_value(entry):
    """What a writer sees of one entry: the slim value plus note, Entity and state."""
    return {**slim(entry), "note": entry.note, "entity_id": str(entry.entity_id), "state": entry.state}


def read_dictionary(*, author, folio_id):
    folio = owned_folio(author, folio_id)
    entries = folio.dictionary_entries.filter(state="active", deleted_at__isnull=True)
    return {"folio_id": str(folio.pk), "dictionary_revision": folio.dictionary_revision,
            "context_revision": folio.context_revision,
            "entries": [entry_value(e) for e in entries] if folio.dictionary_revision is not None else []}


def read_entry(*, author, folio_id, entry_id):
    folio = owned_folio(author, folio_id)
    entry = folio.dictionary_entries.filter(pk=entry_id, deleted_at__isnull=True).first()
    if entry is None:
        raise InterpretationError("not_found", 404)
    revisions = list(entry.revisions.values("revision", "operation", "operation_id", "recorded_at", "dictionary_revision"))
    for revision in revisions:
        revision["operation_id"] = str(revision["operation_id"])
        revision["recorded_at"] = revision["recorded_at"].isoformat()
    return {**entry_value(entry), "revisions": revisions}


# Writing -------------------------------------------------------------------

def add_entry(*, author, folio_id, operation_id, expected_dictionary_revision, shape_id,
              main_name, variants=(), note="", entity_id=None, new_entity_name=None):
    request = {"shape_id": shape_id, "main_name": main_name, "variants": list(variants), "note": note,
               "entity_id": str(entity_id) if entity_id else None, "new_entity_name": new_entity_name,
               "expected_dictionary_revision": expected_dictionary_revision}

    def apply(folio, now):
        _expect(folio, expected_dictionary_revision)
        version = _shape_version(folio, shape_id)
        names = _names(main_name, variants)
        _note(note)
        entity = _entity(author, folio, shape_id, entity_id, new_entity_name)
        if folio.dictionary_entries.filter(entity=entity, shape_id=shape_id, state="active").exists():
            raise InterpretationError("entry_exists", 409)
        entry = FolioDictionaryEntry(folio=folio, entity=entity, shape_id=shape_id, shape_version=version,
            main_name=names[0], variants=names[1], note=note, created_by=author)
        _budget(folio, add=entry)
        entry.save()
        return [(entry, "add")]

    return _command(author, folio_id, "add", operation_id, request, apply)


def edit_entry(*, author, folio_id, entry_id, operation_id, expected_dictionary_revision,
               expected_entry_revision, main_name=None, variants=None, note=None):
    request = {"entry_id": str(entry_id), "main_name": main_name,
               "variants": None if variants is None else list(variants), "note": note,
               "expected_dictionary_revision": expected_dictionary_revision,
               "expected_entry_revision": expected_entry_revision}

    def apply(folio, now):
        _expect(folio, expected_dictionary_revision)
        entry = _active(folio, entry_id, expected_entry_revision)
        names = _names(entry.main_name if main_name is None else main_name,
                       entry.variants if variants is None else variants)
        new_note = entry.note if note is None else note
        _note(new_note)
        if (names[0], names[1], new_note) == (entry.main_name, list(entry.variants), entry.note):
            raise InterpretationError("no_change", 422)
        entry.main_name, entry.variants, entry.note = names[0], names[1], new_note
        entry.revision += 1
        _budget(folio, replace=entry)
        entry.save(update_fields=["main_name", "variants", "note", "revision", "updated_at"])
        return [(entry, "edit")]

    return _command(author, folio_id, "edit", operation_id, request, apply)


def remove_entry(*, author, folio_id, entry_id, operation_id, expected_dictionary_revision, expected_entry_revision):
    """Stop future matching. The entry, its history, its Entity and past decisions stay."""
    request = {"entry_id": str(entry_id), "expected_dictionary_revision": expected_dictionary_revision,
               "expected_entry_revision": expected_entry_revision}

    def apply(folio, now):
        _expect(folio, expected_dictionary_revision)
        entry = _active(folio, entry_id, expected_entry_revision)
        entry.state = "removed"
        entry.revision += 1
        entry.save(update_fields=["state", "revision", "updated_at"])
        return [(entry, "remove")]

    return _command(author, folio_id, "remove", operation_id, request, apply)


def merge_entries(**_):
    raise InterpretationError("merge_not_supported", 422)


def remember(*, author, folio, entity, shape_id, occurrence_text, operation_id, request, now):
    """Confirm and remember's Dictionary half, inside the decision's transaction.

    The caller holds the Folio lock and has already validated the decision.
    Reuses this Entity's active entry for the Shape, adding the occurrence's
    spelling as a variant if it is new; otherwise adds an entry named after
    the Entity. Refuses `dictionary_not_open` if the writer has not opened one.
    """
    if folio.dictionary_revision is None:
        raise InterpretationError("dictionary_not_open", 409)
    from folio.dictionary.matching import equivalent
    version = _shape_version(folio, shape_id)
    entry = (FolioDictionaryEntry.objects.select_for_update()
             .filter(folio=folio, entity=entity, shape_id=shape_id, state="active").first())
    spelling = occurrence_text if isinstance(occurrence_text, str) and occurrence_text.strip() else None
    changes = []
    if entry is None:
        main = entity.name[:MAX_NAME]
        variants = [spelling] if spelling and not equivalent(spelling, main) and len(spelling) <= MAX_NAME else []
        entry = FolioDictionaryEntry(folio=folio, entity=entity, shape_id=shape_id, shape_version=version,
            main_name=main, variants=variants, created_by=author)
        _budget(folio, add=entry)
        entry.save()
        changes.append((entry, "add"))
    elif (spelling and len(spelling) <= MAX_NAME and len(entry.variants) < MAX_VARIANTS
          and not any(equivalent(spelling, name) for name in [entry.main_name, *entry.variants])):
        entry.variants = [*entry.variants, spelling]
        entry.revision += 1
        _budget(folio, replace=entry)
        entry.save(update_fields=["variants", "revision", "updated_at"])
        changes.append((entry, "edit"))
    result = _record(author, folio, changes, operation_id, now) if changes else _result(folio, [])
    result["entry"] = entry_value(entry)
    FolioDictionaryOperation.objects.create(folio=folio, actor=author, operation_id=operation_id, kind="remember",
        request_digest=digest(request), result=result, recorded_at=now)
    return entry, result


# Shared machinery ----------------------------------------------------------

@transaction.atomic
def _command(author, folio_id, kind, operation_id, request, apply):
    folio = owned_folio(author, folio_id, lock=True)
    fingerprint = digest({"kind": kind, **request})
    prior = FolioDictionaryOperation.objects.filter(folio=folio, actor=author, operation_id=operation_id).first()
    if prior is not None:
        if prior.request_digest != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return {**prior.result, "replayed": True}
    if folio.dictionary_revision is None:
        raise InterpretationError("dictionary_not_open", 409)
    now = timezone.now()
    changes = apply(folio, now)
    result = _record(author, folio, changes, operation_id, now)
    result["entry"] = entry_value(changes[0][0])
    FolioDictionaryOperation.objects.create(folio=folio, actor=author, operation_id=operation_id, kind=kind,
        request_digest=fingerprint, result=result, recorded_at=now)
    return {**result, "replayed": False}


def _record(author, folio, changes, operation_id, now):
    folio.dictionary_revision += 1
    folio.context_revision += 1
    folio.save(update_fields=["dictionary_revision", "context_revision", "updated_at"])
    for entry, operation in changes:
        FolioDictionaryEntryRevision.objects.create(entry=entry, revision=entry.revision, operation=operation,
            value=_contour_value(entry, author, operation_id, now), actor=author, operation_id=operation_id,
            recorded_at=now, dictionary_revision=folio.dictionary_revision)
    return _result(folio, changes)


def _result(folio, changes):
    return {"operation": "applied" if changes else "unchanged", "dictionary_revision": folio.dictionary_revision,
            "context_revision": folio.context_revision}


def _contour_value(entry, author, operation_id, now):
    """The full `shared.dictionary_entry` 0.1.0 value, note and provenance included."""
    value = {**slim(entry), "provenance": {"kind": "person", "actor_id": str(author.pk),
        "operation_id": str(operation_id), "recorded_at": now.astimezone(tz.utc).isoformat()}}
    if entry.note:
        value["note"] = entry.note
    return value


def _expect(folio, expected):
    if type(expected) is not int or expected != folio.dictionary_revision:
        raise InterpretationError("dictionary_conflict", 409)


def _active(folio, entry_id, expected_revision):
    entry = (FolioDictionaryEntry.objects.select_for_update()
             .filter(pk=entry_id, folio=folio, deleted_at__isnull=True).first())
    if entry is None:
        raise InterpretationError("not_found", 404)
    if entry.state != "active":
        raise InterpretationError("entry_not_active", 409)
    if type(expected_revision) is not int or expected_revision != entry.revision:
        raise InterpretationError("entry_conflict", 409)
    return entry


def _shape_version(folio, shape_id):
    version = ALLOWED_SHAPES.get(folio.work_type, {}).get(shape_id)
    if version is None:
        raise InterpretationError("unsupported_shape", 422)
    return version


def _plain(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_NAME


def _names(main, variants):
    """Stored exactly as typed; only matching normalizes. Contour's limits."""
    if not _plain(main):
        raise InterpretationError("invalid_name", 422)
    if (not isinstance(variants, (list, tuple)) or len(variants) > MAX_VARIANTS
            or not all(_plain(v) for v in variants) or len(set(variants)) != len(variants)):
        raise InterpretationError("invalid_variants", 422)
    return main, list(variants)


def _note(note):
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise InterpretationError("invalid_note", 422)


def _entity(author, folio, shape_id, entity_id, new_entity_name):
    kind = ENTITY_KIND[shape_id]
    if bool(entity_id) == (new_entity_name is not None):
        raise InterpretationError("invalid_target", 422)
    if entity_id:
        entity = Entity.objects.select_for_update().filter(pk=entity_id, kind=kind, deleted_at__isnull=True,
            sponsor_content_type_id=folio.sponsor_content_type_id, sponsor_object_id=folio.sponsor_object_id).first()
        if entity is None:
            raise InterpretationError("not_found", 404)
        return entity
    if not _plain(new_entity_name):
        raise InterpretationError("invalid_entity_name", 422)
    return Entity.objects.create(kind=kind, name=new_entity_name, sponsor_content_type_id=folio.sponsor_content_type_id,
        sponsor_object_id=folio.sponsor_object_id, created_by=author)


def _budget(folio, *, add=None, replace=None):
    """The size check, against the active snapshot as it would be after this change."""
    entries = []
    for entry in folio.dictionary_entries.filter(state="active", deleted_at__isnull=True):
        entries.append(slim(replace) if replace is not None and entry.pk == replace.pk else slim(entry))
    if add is not None:
        entries.append(slim(add))
    check_budget(folio.dictionary_revision + 1, entries)
