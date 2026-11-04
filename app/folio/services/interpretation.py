"""Folio-owned context commands. No model calls or automatic re-reading."""
from django.db import transaction
from django.utils import timezone

from folio.models import Folio, FolioSightingDecision
from folio.ownership import member_folios
from heddle.bundle import digest
from heddle.errors import InterpretationError
from storyboard.models import Entity

MAX_ENTITIES = 100
MAX_CONTEXT_CHARS = 40000


def owned_folio(author, folio_id, *, lock=False):
    qs = member_folios(author)
    if lock:
        qs = qs.select_for_update()
    folio = qs.filter(pk=folio_id).first()
    if folio is None:
        raise InterpretationError("not_found", 404)
    return folio


def context_snapshot(folio):
    """Recompute live Entity metadata, including edits outside Folio."""
    ids = set()
    for mentions in folio.notes.values_list("mentions", flat=True):
        for mention in mentions or []:
            if isinstance(mention, dict) and mention.get("confirmed_entity_id"):
                ids.add(str(mention["confirmed_entity_id"]))
    ids.update(str(pk) for pk in FolioSightingDecision.objects.filter(
        interpretation__folio_note__folio=folio, disposition="link_entity"
    ).values_list("entity_id", flat=True))
    entities = list(Entity.objects.filter(pk__in=ids, deleted_at__isnull=True,
        sponsor_content_type_id=folio.sponsor_content_type_id,
        sponsor_object_id=folio.sponsor_object_id).order_by("id").values("id", "kind", "name", "aliases"))
    if len(entities) > MAX_ENTITIES:
        raise InterpretationError("context_too_large", 413)
    for entity in entities:
        entity["id"] = str(entity["id"])
    from folio.interpretation.strategy import context_dependencies
    snapshot = {"folio_id": str(folio.pk), "work_type": folio.work_type,
                "title": folio.title, "entities": entities,
                **context_dependencies(), "title_is_writer_set": bool(folio.title)}
    import json
    if len(json.dumps(snapshot, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
        raise InterpretationError("context_too_large", 413)
    return snapshot


def current_context(folio):
    return {"revision": folio.context_revision, **context_snapshot(folio)}


def _replay(folio, request_id, fingerprint):
    entry = folio.prepared_context.get("commands", {}).get(str(request_id))
    if entry:
        if entry["fingerprint"] != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return entry["result"]


def _remember(folio, request_id, fingerprint, result):
    if request_id is None:
        return result
    stored = folio.prepared_context
    commands = dict(stored.get("commands", {}))
    if len(commands) >= 100:
        raise InterpretationError("context_command_limit", 413)
    commands[str(request_id)] = {"fingerprint": fingerprint, "result": result}
    folio.prepared_context = {"snapshot": stored.get("snapshot", stored), "commands": commands}
    folio.save(update_fields=["prepared_context", "updated_at"])
    return result


def _prepare(folio):
    current = context_snapshot(folio)
    if current != folio.prepared_context.get("snapshot", folio.prepared_context):
        folio.context_revision += 1
        folio.prepared_context = {"snapshot": current, "commands": folio.prepared_context.get("commands", {})}
        folio.save(update_fields=["context_revision", "prepared_context", "updated_at"])
    return {"revision": folio.context_revision, **current}


@transaction.atomic
def prepare_context(*, author, folio_id, expected_revision, request_id=None):
    folio = owned_folio(author, folio_id, lock=True)
    fingerprint = digest({"command": "prepare", "expected_revision": expected_revision})
    previous = _replay(folio, request_id, fingerprint) if request_id else None
    if previous is not None:
        return previous
    if folio.context_revision != expected_revision:
        raise InterpretationError("context_conflict", 409)
    return _remember(folio, request_id, fingerprint, _prepare(folio))


@transaction.atomic
def change_orientation(*, author, folio_id, expected_revision=None, title=None, work_type=None):
    folio = owned_folio(author, folio_id, lock=True)
    if expected_revision is not None and folio.context_revision != expected_revision:
        raise InterpretationError("context_conflict", 409)
    if work_type is not None and work_type not in ("", "fiction"):
        raise InterpretationError("unsupported_work_type", 422)
    if title is not None and (not isinstance(title, str) or len(title) > 255):
        raise InterpretationError("invalid_title", 422)
    previous_type = folio.work_type
    changed = (title is not None and title != folio.title) or (work_type is not None and work_type != folio.work_type)
    if changed:
        if title is not None:
            folio.title = title
        if work_type is not None:
            folio.work_type = work_type
        folio.orientation_confirmed_by = None
        folio.orientation_confirmed_at = None
        folio.orientation_confirmed_digest = ""
        folio.save()  # BaseContent owns the title/slug lifecycle.
    context = _prepare(folio)
    return {"context": context, "rereading_suggestion": (
        "The work type changed; earlier findings may need another reading."
        if previous_type != folio.work_type else None)}


@transaction.atomic
def confirm_orientation(*, author, folio_id, expected_digest, title, work_type, request_id=None):
    folio = owned_folio(author, folio_id, lock=True)
    fingerprint = digest({"command": "confirm", "expected_digest": expected_digest,
                          "title": title, "work_type": work_type})
    previous = _replay(folio, request_id, fingerprint) if request_id else None
    if previous is not None:
        return previous
    context = current_context(folio)
    if digest(context) != expected_digest or title != folio.title or work_type != folio.work_type:
        raise InterpretationError("context_conflict", 409)
    if work_type != "fiction":
        raise InterpretationError("unsupported_work_type", 422)
    folio.orientation_confirmed_by = author
    folio.orientation_confirmed_at = timezone.now()
    folio.orientation_confirmed_digest = digest({"title": title, "work_type": work_type})
    folio.save(update_fields=["orientation_confirmed_by", "orientation_confirmed_at", "orientation_confirmed_digest", "updated_at"])
    return _remember(folio, request_id, fingerprint, context)


@transaction.atomic
def decide_sighting(*, author, interpretation_id, attempt_id, sighting_id,
                    request_id, disposition, reviewed_digest, reaffirmed=False,
                    clarification="", entity_id=None, new_entity_name=None):
    """Resolve the server's checked occurrence, never a caller-supplied Sighting."""
    from folio.models import FolioInterpretation
    from heddle.handoff import keep_sighting
    from heddle.steps import identity
    from initiatives.models import ActionRun

    record = FolioInterpretation.objects.filter(pk=interpretation_id, initiated_by=author).first()
    if record is None:
        raise InterpretationError("not_found", 404)
    folio = owned_folio(author, record.folio_note.folio_id, lock=True)
    record = FolioInterpretation.objects.select_for_update().get(pk=record.pk)
    parent = ActionRun.objects.select_for_update().get(pk=record.action_run_id)
    if parent.initiator_id != str(author.pk):
        raise InterpretationError("not_found", 404)
    command = {"attempt_id": str(attempt_id), "sighting_id": sighting_id,
        "disposition": disposition, "reviewed_digest": reviewed_digest,
        "reaffirmed": reaffirmed, "clarification": clarification,
        "entity_id": str(entity_id) if entity_id else None, "new_entity_name": new_entity_name}
    fingerprint = digest(command)
    prior = record.decisions.filter(actor=author, request_id=request_id).first()
    if prior:
        if prior.request_digest != fingerprint:
            raise InterpretationError("request_conflict", 409)
        return prior
    context = current_context(folio)
    if digest(context) != reviewed_digest:
        raise InterpretationError("context_conflict", 409)
    state = (parent.request_payload or {}).get("interpretation", {})
    attempts = [state, *state.get("history", [])]
    attempt = next((a for a in attempts if a.get("attempt_id") == str(attempt_id)
        and a.get("findings") and (a.get("previous_status", a.get("status")) == "succeeded")), None)
    if attempt is None or not isinstance(attempt.get("context"), dict):
        raise InterpretationError("checked_attempt_not_found", 409)
    original_context = attempt["context"]
    if original_context.get("folio_id") != str(folio.pk):
        raise InterpretationError("context_conflict", 409)
    if digest(original_context) != digest(context) and reaffirmed is not True:
        raise InterpretationError("reaffirmation_required", 409)
    sightings = attempt["findings"].get("sightings", [])
    matches = [s for s in sightings if s.get("sighting_id") == sighting_id]
    if len(matches) != 1:
        raise InterpretationError("sighting_not_found", 404)
    if record.decisions.filter(attempt_id=attempt_id, sighting_id=sighting_id).exists():
        raise InterpretationError("decision_exists", 409)
    sighting = matches[0]
    provisional = entity = None
    if disposition == "defer":
        if entity_id or new_entity_name is not None:
            raise InterpretationError("invalid_target", 422)
        provisional = keep_sighting(sighting=sighting, action_run=parent, owner_user=author)
    elif disposition == "link_entity":
        kind = {"writing.character": "character", "writing.setting": "setting"}.get(sighting["shape_id"])
        if kind is None or bool(entity_id) == (new_entity_name is not None):
            raise InterpretationError("invalid_target", 422)
        if entity_id:
            entity = Entity.objects.select_for_update().filter(pk=entity_id, kind=kind,
                deleted_at__isnull=True, sponsor_content_type_id=folio.sponsor_content_type_id,
                sponsor_object_id=folio.sponsor_object_id).first()
            if entity is None:
                raise InterpretationError("not_found", 404)
        else:
            if not isinstance(new_entity_name, str) or not new_entity_name.strip() or len(new_entity_name) > 255:
                raise InterpretationError("invalid_entity_name", 422)
            entity = Entity.objects.create(kind=kind, name=new_entity_name,
                sponsor_content_type_id=folio.sponsor_content_type_id,
                sponsor_object_id=folio.sponsor_object_id, created_by=author)
    elif disposition != "dismiss" or entity_id or new_entity_name is not None:
        raise InterpretationError("invalid_disposition", 422)
    decision = FolioSightingDecision.objects.create(interpretation=record,
        actor=author, attempt_id=attempt_id, sighting_id=sighting_id,
        disposition=disposition, request_id=request_id, request_digest=fingerprint,
        original_context=original_context, reviewed_context=context,
        original_identity=identity(attempt) if "sources" in attempt else {
            k: attempt[k] for k in ("revision", "source_digest", "context_revision", "context_digest")},
        reaffirmed=reaffirmed, clarification=clarification,
        provisional_data=provisional, entity=entity)
    if entity:
        _prepare(folio)
    return decision
