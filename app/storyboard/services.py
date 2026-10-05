# storyboard/services.py
#
# Tree-validation rules enforced at the service boundary, not just at
# creation (build-handoff §3): parent validity against the storyboard's
# grammar, cycle prevention on reparent, and no cross-Storyboard moves.

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from .grammars import get_grammar
from .models import Storyboard, StoryboardItem


def _ancestor_ids(item: StoryboardItem) -> set:
    ids = set()
    current = item.parent
    while current is not None:
        ids.add(current.id)
        current = current.parent
    return ids


def validate_parent(storyboard: Storyboard, level: str, parent: StoryboardItem | None) -> None:
    grammar = get_grammar(storyboard.grammar)
    if level not in grammar.levels:
        raise ValidationError(f"Grammar {storyboard.grammar!r} does not define level {level!r}.")
    allowed = grammar.allowed_parents.get(level, [])
    parent_level = parent.level if parent is not None else None
    if parent_level not in allowed:
        raise ValidationError(
            f"{level!r} may not be parented under {parent_level!r} in grammar {storyboard.grammar!r}."
        )


@transaction.atomic
def create_item(
    *,
    storyboard: Storyboard,
    level: str,
    parent: StoryboardItem | None = None,
    title: str = "",
    reference=None,
    rank: int | None = None,
    head=None,
) -> StoryboardItem:
    validate_parent(storyboard, level, parent)
    if parent is not None and parent.storyboard_id != storyboard.id:
        raise ValidationError("Parent must belong to the same Storyboard.")

    if rank is None:
        last = (
            StoryboardItem.objects.filter(storyboard=storyboard, parent=parent)
            .order_by("-rank")
            .first()
        )
        rank = (last.rank + 1) if last else 0

    item = StoryboardItem.objects.create(
        storyboard=storyboard,
        parent=parent,
        level=level,
        title=title,
        rank=rank,
        head=head,
    )
    if reference is not None:
        item.reference = reference
        item.save(update_fields=["reference_content_type", "reference_object_id"])
    return item


@transaction.atomic
def reparent_item(
    *,
    item: StoryboardItem,
    new_parent: StoryboardItem | None,
    new_rank: int | None = None,
) -> StoryboardItem:
    # No cross-Storyboard moves, full stop, for v1 (build-handoff §3).
    if new_parent is not None and new_parent.storyboard_id != item.storyboard_id:
        raise ValidationError("Cannot move a StoryboardItem to a different Storyboard.")

    validate_parent(item.storyboard, item.level, new_parent)

    if new_parent is not None:
        # Cycle prevention: the item being moved must not already be an
        # ancestor of (or equal to) the proposed new parent.
        blocked = _ancestor_ids(new_parent) | {new_parent.id}
        if item.id in blocked:
            raise ValidationError("Cannot reparent an item under its own descendant (cycle).")

    item.parent = new_parent
    if new_rank is not None:
        item.rank = new_rank
    item.save(update_fields=["parent", "rank", "updated_at"])
    return item


@transaction.atomic
def reorder_siblings(
    *,
    storyboard: Storyboard,
    parent: StoryboardItem | None,
    ordered_item_ids: list,
) -> None:
    """Deliberately reorder a story: set rank from the given sibling order."""
    siblings = {
        str(i.id): i
        for i in StoryboardItem.objects.filter(storyboard=storyboard, parent=parent)
    }
    for rank, item_id in enumerate(ordered_item_ids):
        item = siblings.get(str(item_id))
        if item is None:
            raise ValidationError(f"Item {item_id} is not a sibling of this group.")
        if item.rank != rank:
            item.rank = rank
            item.save(update_fields=["rank", "updated_at"])


@transaction.atomic
def create_scene(
    *,
    storyboard: Storyboard,
    parent: StoryboardItem,
    title: str = "",
    rank: int | None = None,
):
    """
    Create a Scene StoryboardItem together with the WritingPiece that
    carries its prose. The WritingPiece composes through authorship, not a
    separate bypass (build-handoff §2a): author and sponsor are inherited
    from the Storyboard, never derived from the request context.
    """
    from writing.models import WritingPiece

    validate_parent(storyboard, "scene", parent)
    if parent.storyboard_id != storyboard.id:
        raise ValidationError("A Scene's parent Chapter must belong to the same Storyboard.")

    piece = WritingPiece.objects.create(
        title=title,
        writing_kind="scene",
        body_json={},
        author=storyboard.created_by,
        sponsor_content_type=storyboard.sponsor_content_type,
        sponsor_object_id=storyboard.sponsor_object_id,
    )
    return create_item(
        storyboard=storyboard,
        level="scene",
        parent=parent,
        title=title,
        reference=piece,
        rank=rank,
    )
