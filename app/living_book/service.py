from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from relations.models import Relationship
from relations.service import RelationshipService

from .models import LivingBook

_CONTAINS_SLUG = "contains"
_MAX_DEPTH = 4


class LivingBookService:

    # -------------------------------------------------------------------------
    # Promotion (LB → creation)
    # -------------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def promote_to_living_book(
        piece,
        *,
        title: str,
        description: str = "",
        sponsor=None,
        created_by,
    ) -> LivingBook:
        """
        Promote a WritingPiece to the trunk of a new LivingBook.
        Requires an active Dispatch on the piece (OQ-6).
        Single-trunk constraint: a piece may only be trunk in one active LivingBook.
        """
        if not _has_active_dispatch(piece):
            raise ValueError("WritingPiece must have an active Dispatch before promotion.")

        if LivingBook.objects.filter(
            trunk=piece, status__in=(LivingBook.STATUS_DRAFT, LivingBook.STATUS_ACTIVE)
        ).exists():
            raise ValueError("This piece is already the trunk of an active Living Book.")

        sponsor_ct = None
        sponsor_id = None
        if sponsor is not None:
            sponsor_ct = ContentType.objects.get_for_model(sponsor.__class__)
            sponsor_id = sponsor.pk

        return LivingBook.objects.create(
            title=title,
            description=description,
            trunk=piece,
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
            status=LivingBook.STATUS_DRAFT,
            created_by=created_by,
        )

    # -------------------------------------------------------------------------
    # Tree manipulation
    # -------------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def add_node(
        living_book: LivingBook,
        piece,
        *,
        parent=None,
        position: int | None = None,
        created_by,
    ) -> Relationship:
        """
        Add an existing WritingPiece as a node in the tree.
        parent=None → child of LivingBook root.
        Single-membership constraint: piece may not already appear as an active node.
        """
        _assert_not_already_in_tree(living_book, piece)
        _assert_depth_ok(living_book, parent)

        source = parent if parent is not None else living_book
        if position is None:
            position = _next_sibling_position(source)

        return RelationshipService.create_relationship(
            type_slug=_CONTAINS_SLUG,
            source=source,
            target=piece,
            created_by=created_by,
            position=position,
        )

    @staticmethod
    @transaction.atomic
    def create_and_add_node(
        living_book: LivingBook,
        *,
        parent=None,
        position: int | None = None,
        author,
        title: str = "",
    ):
        """
        Create a new WritingPiece with a placeholder title and add it to the tree.
        Returns (WritingPiece, Relationship).
        """
        from writing.models import WritingPiece

        _assert_depth_ok(living_book, parent)

        piece = WritingPiece.objects.create(
            title=title or _placeholder_title(living_book, parent),
            author=author,
            writing_kind="dispatch",
        )
        rel = LivingBookService.add_node(
            living_book, piece, parent=parent, position=position, created_by=author
        )
        return piece, rel

    @staticmethod
    @transaction.atomic
    def remove_node(living_book: LivingBook, piece, *, removed_by=None) -> None:
        """
        Remove a WritingPiece from the tree by archiving its Relationship.
        Does not recursively remove children — children become orphaned.
        """
        source_ct = ContentType.objects.get_for_model(living_book.__class__)
        piece_ct = ContentType.objects.get_for_model(piece.__class__)

        # Could be attached to LivingBook root or a parent WritingPiece
        rel = Relationship.objects.filter(
            target_content_type=piece_ct,
            target_object_id=piece.pk,
            relationship_type__slug=_CONTAINS_SLUG,
            status=Relationship.STATUS_ACTIVE,
        ).filter(
            # In this tree: source is either the living book or another piece in this tree
            source_object_id__in=_all_node_ids(living_book)
        ).first()

        if rel is None:
            raise ValueError("WritingPiece is not an active node in this Living Book.")

        RelationshipService.archive_relationship(
            relationship_id=rel.id, archived_by=removed_by
        )

    @staticmethod
    @transaction.atomic
    def reorder_siblings(living_book: LivingBook, parent, ordered_piece_ids: list) -> list:
        """
        Reassign position values for siblings under parent (LivingBook or WritingPiece).
        ordered_piece_ids is the desired sibling order (all siblings must be present).
        Returns updated Relationship records.
        """
        parent_ct = ContentType.objects.get_for_model(parent.__class__)
        piece_ct = ContentType.objects.get_for_model(
            __import__("writing.models", fromlist=["WritingPiece"]).WritingPiece
        )

        siblings = {
            str(r.target_object_id): r
            for r in Relationship.objects.filter(
                source_content_type=parent_ct,
                source_object_id=parent.pk,
                relationship_type__slug=_CONTAINS_SLUG,
                status=Relationship.STATUS_ACTIVE,
            ).select_for_update()
        }

        updated = []
        for pos, pid in enumerate(ordered_piece_ids):
            rel = siblings.get(str(pid))
            if rel is None:
                raise ValueError(f"Piece {pid} is not a direct child of this parent.")
            rel.position = pos
            rel.save(update_fields=["position", "updated_at"])
            updated.append(rel)
        return updated

    # -------------------------------------------------------------------------
    # Read views
    # -------------------------------------------------------------------------

    @staticmethod
    def get_tree(living_book: LivingBook, *, for_editor: bool = False) -> list:
        """
        DFS tree starting from LivingBook root. Returns ordered list of dicts.
        for_editor=False → published nodes only; for_editor=True → all nodes.
        """
        nodes = RelationshipService.get_tree(living_book, type_slug=_CONTAINS_SLUG, max_depth=_MAX_DEPTH)
        if not for_editor:
            nodes = [n for n in nodes if _is_published(n["obj"])]
        return nodes

    @staticmethod
    def get_context_neighbors(living_book: LivingBook, piece, *, for_editor: bool = False):
        """
        Return (prev_piece, next_piece) in DFS order for Context Flow Mode.
        Returns None for missing neighbors.
        """
        flat = LivingBookService.get_tree(living_book, for_editor=for_editor)
        pieces = [n["obj"] for n in flat]
        try:
            idx = next(i for i, p in enumerate(pieces) if p.pk == piece.pk)
        except StopIteration:
            return None, None
        prev_p = pieces[idx - 1] if idx > 0 else None
        next_p = pieces[idx + 1] if idx < len(pieces) - 1 else None
        return prev_p, next_p

    @staticmethod
    def get_accumulated_view(living_book: LivingBook, *, for_editor: bool = False) -> list:
        """
        Flat DFS list of nodes for the Accumulated Read View.
        Each entry: {piece, depth, position, title, body_excerpt, word_count, is_published}.
        """
        flat = LivingBookService.get_tree(living_book, for_editor=for_editor)
        result = []
        for node in flat:
            p = node["obj"]
            result.append({
                "piece_id": str(p.pk),
                "piece_slug": getattr(p, "slug", None),
                "title": p.title or "Untitled",
                "body": getattr(p, "body", "") or "",
                "word_count": _word_count(getattr(p, "body", "") or ""),
                "is_published": _is_published(p),
                "depth": node["depth"],
                "position": node["position"],
            })
        return result


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _has_active_dispatch(piece) -> bool:
    dc = getattr(piece, "dispatch_content", None)
    if dc is None:
        return False
    return not getattr(dc, "is_archived", False)


def _is_published(piece) -> bool:
    status = getattr(piece, "status", None)
    if status is None:
        return False
    return str(status).lower() in ("published", "public")


def _next_sibling_position(source) -> int:
    ct = ContentType.objects.get_for_model(source.__class__)
    last = (
        Relationship.objects.filter(
            source_content_type=ct,
            source_object_id=source.pk,
            relationship_type__slug=_CONTAINS_SLUG,
            status=Relationship.STATUS_ACTIVE,
        )
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
    )
    return (last or -1) + 1


def _all_node_ids(living_book: LivingBook) -> set:
    """Return all object IDs that appear as source or target in this tree."""
    lb_ct = ContentType.objects.get_for_model(LivingBook)
    ids = {living_book.pk}

    def _collect(ct_id, obj_id):
        children = Relationship.objects.filter(
            source_content_type_id=ct_id,
            source_object_id=obj_id,
            relationship_type__slug=_CONTAINS_SLUG,
            status=Relationship.STATUS_ACTIVE,
        ).values_list("target_content_type_id", "target_object_id")
        for child_ct_id, child_id in children:
            if child_id not in ids:
                ids.add(child_id)
                _collect(child_ct_id, child_id)

    _collect(lb_ct.pk, living_book.pk)
    return ids


def _assert_not_already_in_tree(living_book: LivingBook, piece) -> None:
    piece_ct = ContentType.objects.get_for_model(piece.__class__)
    all_ids = _all_node_ids(living_book)
    if piece.pk in all_ids:
        raise ValueError("This piece is already in the Living Book tree.")


def _assert_depth_ok(living_book: LivingBook, parent) -> None:
    if parent is None:
        return
    # parent is a WritingPiece; find its depth by walking up
    piece_ct = ContentType.objects.get_for_model(parent.__class__)
    depth = 1
    obj_id = parent.pk
    for _ in range(_MAX_DEPTH):
        rel = Relationship.objects.filter(
            target_content_type=piece_ct,
            target_object_id=obj_id,
            relationship_type__slug=_CONTAINS_SLUG,
            status=Relationship.STATUS_ACTIVE,
        ).select_related("source_content_type").first()
        if rel is None:
            break
        depth += 1
        if rel.source_content_type.app_label == "living_book":
            break
        obj_id = rel.source_object_id
    if depth >= _MAX_DEPTH:
        raise ValueError(f"Tree depth limit ({_MAX_DEPTH}) would be exceeded.")


def _placeholder_title(living_book: LivingBook, parent) -> str:
    if parent is None:
        return "Untitled branch"
    return "Untitled leaf"


def _word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0
