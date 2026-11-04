"""Folio authority/source adapter; Heddle owns all interpretation history.

The reviewed Reading is injected. No capability registration or execution here.
"""
from django.conf import settings
from django.db import transaction
from folio.models import FolioNote, FolioInterpretation
from folio.services.interpretation import owned_folio, current_context, _prepare
from heddle import lifecycle as heddle
from heddle.errors import InterpretationError
from initiatives.models import ActionRun


def context_provider(author, parent):
    refs = parent.request_payload["folio_source"]
    folio = owned_folio(author, refs["folio_id"])
    if not FolioNote.objects.filter(pk=refs["note_id"], folio=folio, deleted_at__isnull=True).exists():
        raise InterpretationError("note_moved_or_unavailable", 409)
    return current_context(folio)


def _public(parent, reading, record):
    result = heddle.snapshot(parent, reading=reading)
    result.pop("weave_action_run_id", None)
    return {**result, "reading_id": str(record.pk), "action_run_id": str(parent.pk)}


@transaction.atomic
def begin_reading(*, author, folio_id, note_id, request_id, reading):
    folio = owned_folio(author, folio_id, lock=True)
    note = FolioNote.objects.select_for_update().filter(pk=note_id, folio=folio, deleted_at__isnull=True).first()
    if note is None:
        raise InterpretationError("not_found", 404)
    if folio.work_type != "fiction":
        raise InterpretationError("fiction_selection_required", 409)
    if note.status != "ready" or not note.text.strip():
        raise InterpretationError("source_not_ready", 409)
    if len(note.text) > 40000:
        raise InterpretationError("source_too_long", 413)
    _prepare(folio)
    record = FolioInterpretation.objects.filter(folio_note=note, initiated_by=author).first()
    if record:
        parent = heddle.owned_parent(record.action_run_id, author, tool_name=reading.tool_name, lock=True)
        context_provider(author, parent)
        return _public(parent, reading, record)

    def parent_factory():
        return ActionRun.objects.create(tool_name=reading.tool_name, status="pending",
            tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")),
            tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")),
            initiator_type="human", initiator_id=str(author.pk),
            request_payload={"folio_source": {"folio_id": str(folio.pk), "note_id": str(note.pk)}})

    parent, _ = heddle.begin(author=author, request_id=request_id, reading=reading,
        parent_factory=parent_factory, source_ref=f"folio_note:{note.pk}", source_text=note.text,
        conflict_key="note_id", conflict_value=str(note.pk))
    record = FolioInterpretation.objects.create(folio_note=note, action_run=parent, initiated_by=author)
    return _public(parent, reading, record)


def inspect_reading(*, author, folio_id, note_id, reading_id, reading):
    folio = owned_folio(author, folio_id)
    record = FolioInterpretation.objects.filter(pk=reading_id, initiated_by=author,
        folio_note_id=note_id, folio_note__folio=folio, folio_note__deleted_at__isnull=True).first()
    if record is None:
        raise InterpretationError("not_found", 404)
    parent = heddle.owned_parent(record.action_run_id, author, tool_name=reading.tool_name)
    context_provider(author, parent)
    return _public(parent, reading, record)
