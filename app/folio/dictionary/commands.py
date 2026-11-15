"""Dictionary write paths. This unit has one: opening an empty Dictionary.

Adding, editing, merging and removing entries, and their receipts, are the
next unit; each must call `budget.check_budget` before it writes.
"""
from django.db import transaction

from folio.services.interpretation import owned_folio


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
