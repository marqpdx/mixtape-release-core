"""Owner-authorized, replay-safe local-only restriction. No dispatch on change."""
from django.db import transaction
from folio.services.interpretation import owned_folio, _prepare, _replay, _remember
from heddle.bundle import digest
from heddle.errors import InterpretationError


@transaction.atomic
def change_local_only(*, author, folio_id, local_only, expected_revision, request_id):
    folio = owned_folio(author, folio_id, lock=True)
    if type(local_only) is not bool or type(expected_revision) is not int:
        raise InterpretationError("invalid_policy", 422)
    fingerprint = digest({"command": "local_only", "local_only": local_only,
                          "expected_revision": expected_revision})
    previous = _replay(folio, request_id, fingerprint)
    if previous is not None:
        return previous
    if folio.context_revision != expected_revision:
        raise InterpretationError("context_conflict", 409)
    folio.local_only = local_only
    folio.save(update_fields=["local_only", "updated_at"])
    return _remember(folio, request_id, fingerprint, _prepare(folio))
