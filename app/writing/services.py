# apps/writing/services.py
from django.db import transaction

from .models import Seed
from .utils import first_line_as_title, plaintext_to_tiptap_json


class PromotionError(Exception):
    pass

@transaction.atomic
def promote_seed_to_working_copy(*, seed: Seed, requested_by, extra_meta: dict | None = None):
    """
    Idempotently create a WorkingCopy from a Seed.
    """
    if seed.author_id != requested_by.id and not getattr(requested_by, "is_staff", False):
        raise PromotionError("Not allowed to promote this seed.")
    if seed.promoted_to_id:
        return seed.promoted_to

    # Lazy import to avoid circular refs
    from .models import WritingWorkingCopy

    title = first_line_as_title(seed.body_text) or "Untitled"
    body_json = plaintext_to_tiptap_json(seed.body_text)

    wc = WritingWorkingCopy.objects.create(
        author=seed.author,
        title=title,
        body_json=body_json,
        **(extra_meta or {})
    )
    seed.promoted_to = wc
    seed.save(update_fields=["promoted_to", "updated_at"])
    return wc
