# apps/writing/services.py
from django.db import transaction
from django.utils import timezone

from .models import Seed, WritingPiece
from .utils import first_line_as_title, plaintext_to_tiptap_json
from utils.shared.contenttypes import resolve_content_type
from utils.writing.writing_utils import generate_excerpt, generate_excerpt_from_prosemirror


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
    from .models import WorkingDocument

    title = first_line_as_title(seed.body_text) or "Untitled"
    body_json = plaintext_to_tiptap_json(seed.body_text)
    excerpt = generate_excerpt(seed.body_text or "", max_length=280)

    piece = WritingPiece(
        author=seed.author,
        title=title,
        excerpt=excerpt,
        body_json=body_json,
        writing_kind="post",
        status="draft",
    )
    sponsor_ct_raw = (extra_meta or {}).get("sponsor_content_type")
    sponsor_object_id = (extra_meta or {}).get("sponsor_object_id")
    if sponsor_ct_raw and sponsor_object_id:
        piece.sponsor_content_type = resolve_content_type(sponsor_ct_raw)
        piece.sponsor_object_id = sponsor_object_id
    else:
        # Temporary rule: promoted personal drafts sponsor to the user until
        # group storyline sponsorship is defined.
        piece.set_sponsor(seed.author)
    if seed.author_id:
        piece.set_submitted_by(seed.author)
    piece.save()

    wc = WorkingDocument.objects.create(
        piece=piece,
        user=requested_by,
        title=title,
        excerpt=excerpt,
        body_json=body_json,
    )
    seed.promoted_to = wc
    seed.save(update_fields=["promoted_to", "updated_at"])
    return wc


# ============================================================================
# Leaf Services — Storyline content
# ============================================================================

@transaction.atomic
def promote_seed_to_leaf(*, seed: Seed, author):
    """
    Promote a Seed into a Leaf on the author's Storyline.
    Called from the Draftroom as a curation step.

    - Creates Leaf with origin_seed reference
    - Sets published_at to now
    - Does NOT delete the Seed (user chooses)
    """
    from .models import Leaf

    if seed.author_id != author.id:
        raise PromotionError("Not allowed to promote this seed.")

    body_json = plaintext_to_tiptap_json(seed.body_text) if seed.body_text else {}
    kind = "voice" if seed.kind == "voice" else "text"

    leaf = Leaf.objects.create(
        author=author,
        body_text=seed.body_text,
        body_json=body_json,
        kind=kind,
        origin_seed=seed,
        audio_file=seed.audio_file if kind == "voice" else None,
        published_at=timezone.now(),
    )
    return leaf


@transaction.atomic
def quick_post_leaf(*, author, body_text="", body_json=None, kind="text",
                    audio_file=None, image_file=None, link_url=None,
                    publish=True):
    """
    Create a Leaf directly from the Composer.
    Creates a Seed for provenance, then creates a Leaf.
    If publish=False, the Leaf is saved as a draft (published_at=None).
    """
    from .models import Leaf

    # Create a Seed for provenance
    seed = Seed.objects.create(
        author=author,
        body_text=body_text,
        kind="voice" if kind == "voice" else "text",
        audio_file=audio_file,
    )

    if body_json is None:
        body_json = plaintext_to_tiptap_json(body_text) if body_text else {}

    leaf = Leaf.objects.create(
        author=author,
        body_text=body_text,
        body_json=body_json,
        kind=kind,
        origin_seed=seed,
        audio_file=audio_file,
        image_file=image_file,
        link_url=link_url,
        published_at=timezone.now() if publish else None,
    )
    return leaf


@transaction.atomic
def create_reference_leaf(*, author, source_object, caption="", image_file=None):
    """
    Create a reference Leaf — a curated card pointing to other content.
    The author writes original commentary (not copied from source).
    """
    from .models import Leaf

    ct = ContentType.objects.get_for_model(source_object)

    leaf = Leaf.objects.create(
        author=author,
        caption=caption,
        kind="text",
        source_content_type=ct,
        source_object_id=source_object.pk,
        image_file=image_file,
        published_at=timezone.now(),
    )
    return leaf


@transaction.atomic
def promote_leaf_to_working_copy(*, leaf, author, extra_meta: dict | None = None):
    """
    Promote a Leaf to a WritingPiece draft (WorkingDocument).
    Follows the same pattern as promote_seed_to_working_copy.
    """
    from .models import Leaf, WorkingDocument

    if leaf.author_id != author.id:
        raise PromotionError("Not allowed to promote this leaf.")
    if leaf.promoted_to_id:
        return leaf.promoted_to

    title = first_line_as_title(leaf.body_text) or "Untitled"
    body_json = leaf.body_json if leaf.body_json else plaintext_to_tiptap_json(leaf.body_text)
    if leaf.caption:
        # Caption is plain author commentary, not structured ProseMirror content.
        excerpt = generate_excerpt(leaf.caption, max_length=280)
    else:
        # Leaf bodies are real ProseMirror content (rich text + images per the
        # model docstring) — skip headings/images to find the first real
        # paragraph, same approach as markdown import's resolve_excerpt().
        excerpt = generate_excerpt_from_prosemirror(body_json, max_length=280)
        if not excerpt:
            excerpt = generate_excerpt(leaf.body_text or "", max_length=280)

    piece = WritingPiece(
        author=author,
        title=title,
        excerpt=excerpt,
        body_json=body_json,
        writing_kind="post",
        status="draft",
    )
    sponsor_ct_raw = (extra_meta or {}).get("sponsor_content_type")
    sponsor_object_id = (extra_meta or {}).get("sponsor_object_id")
    if sponsor_ct_raw and sponsor_object_id:
        piece.sponsor_content_type = resolve_content_type(sponsor_ct_raw)
        piece.sponsor_object_id = sponsor_object_id
    else:
        # Temporary rule: promoted personal drafts sponsor to the user until
        # group storyline sponsorship is defined.
        piece.set_sponsor(author)
    piece.set_submitted_by(author)
    piece.save()

    wc = WorkingDocument.objects.create(
        piece=piece,
        user=author,
        title=title,
        excerpt=excerpt,
        body_json=body_json,
    )
    leaf.promoted_to = wc
    leaf.save(update_fields=["promoted_to", "updated_at"])
    return wc
