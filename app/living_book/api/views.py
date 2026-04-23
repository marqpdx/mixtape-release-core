from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece

from ..models import LivingBook
from ..service import LivingBookService


# -------------------------------------------------------------------------
# Serialization helpers
# -------------------------------------------------------------------------

def _serialize_piece_stub(piece):
    return {
        "id": str(piece.pk),
        "slug": getattr(piece, "slug", None),
        "title": piece.title or "Untitled",
        "word_count": len((getattr(piece, "body", "") or "").split()),
        "is_published": _is_published(piece),
        "updated_at": piece.updated_at,
    }


def _serialize_living_book(lb):
    return {
        "id": str(lb.pk),
        "title": lb.title,
        "description": lb.description,
        "status": lb.status,
        "trunk": _serialize_piece_stub(lb.trunk) if lb.trunk_id else None,
        "created_by": str(lb.created_by_id) if lb.created_by_id else None,
        "created_at": lb.created_at,
        "updated_at": lb.updated_at,
    }


def _serialize_tree_node(node):
    piece = node["obj"]
    return {
        "piece": _serialize_piece_stub(piece),
        "depth": node["depth"],
        "position": node["position"],
        "relationship_id": str(node["relationship"].id),
    }


def _serialize_context_piece(piece):
    if piece is None:
        return None
    body = getattr(piece, "body", "") or ""
    # First paragraph up to ~500 chars at paragraph boundary
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    excerpt = paragraphs[0][:500] if paragraphs else ""
    return {
        "id": str(piece.pk),
        "slug": getattr(piece, "slug", None),
        "title": piece.title or "Untitled",
        "excerpt": excerpt,
    }


def _is_published(piece) -> bool:
    status = getattr(piece, "status", None)
    return str(status).lower() in ("published", "public") if status else False


def _for_editor(request, lb) -> bool:
    """True if the requesting user is an editor (author of trunk or superuser)."""
    if request.user.is_superuser:
        return True
    return lb.trunk_id and lb.trunk.author_id == request.user.pk


# -------------------------------------------------------------------------
# Views
# -------------------------------------------------------------------------

class LivingBookListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        books = LivingBook.objects.filter(
            status__in=(LivingBook.STATUS_DRAFT, LivingBook.STATUS_ACTIVE)
        ).select_related("trunk", "created_by")
        return Response([_serialize_living_book(lb) for lb in books])

    def post(self, request):
        piece_slug = request.data.get("piece_slug")
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "")

        if not piece_slug:
            return Response({"detail": "piece_slug required."}, status=400)
        if not title:
            return Response({"detail": "title required."}, status=400)

        piece = get_object_or_404(WritingPiece, slug=piece_slug)
        if piece.author_id != request.user.pk and not request.user.is_superuser:
            return Response({"detail": "Not authorized."}, status=403)

        try:
            lb = LivingBookService.promote_to_living_book(
                piece,
                title=title,
                description=description,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(_serialize_living_book(lb), status=201)


class LivingBookDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        return Response(_serialize_living_book(lb))

    def patch(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        for field in ("title", "description", "status"):
            if field in request.data:
                setattr(lb, field, request.data[field])
        lb.save()
        return Response(_serialize_living_book(lb))


class LivingBookTreeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        nodes = LivingBookService.get_tree(lb, for_editor=_for_editor(request, lb))
        return Response({
            "living_book": _serialize_living_book(lb),
            "nodes": [_serialize_tree_node(n) for n in nodes],
        })


class LivingBookAccumulatedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        sections = LivingBookService.get_accumulated_view(lb, for_editor=_for_editor(request, lb))
        return Response({
            "living_book_id": str(lb.pk),
            "title": lb.title,
            "sections": sections,
        })


class LivingBookNodeAddView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        piece_slug = request.data.get("piece_slug")
        parent_id = request.data.get("parent_id")
        position = request.data.get("position")

        if not piece_slug:
            return Response({"detail": "piece_slug required."}, status=400)

        piece = get_object_or_404(WritingPiece, slug=piece_slug)
        parent = None
        if parent_id:
            parent = get_object_or_404(WritingPiece, pk=parent_id)

        try:
            rel = LivingBookService.add_node(
                lb, piece, parent=parent,
                position=int(position) if position is not None else None,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "relationship_id": str(rel.id),
            "piece": _serialize_piece_stub(piece),
            "position": rel.position,
        }, status=201)


class LivingBookNodeCreateAddView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        lb = get_object_or_404(LivingBook, pk=pk)
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        parent_id = request.data.get("parent_id")
        position = request.data.get("position")
        title = request.data.get("title", "")

        parent = None
        if parent_id:
            parent = get_object_or_404(WritingPiece, pk=parent_id)

        try:
            piece, rel = LivingBookService.create_and_add_node(
                lb, parent=parent,
                position=int(position) if position is not None else None,
                author=request.user,
                title=title,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "relationship_id": str(rel.id),
            "piece": _serialize_piece_stub(piece),
            "position": rel.position,
        }, status=201)


class LivingBookNodeReorderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk, piece_id):
        lb = get_object_or_404(LivingBook, pk=pk)
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        ordered_ids = request.data.get("ordered_ids", [])
        if not ordered_ids:
            return Response({"detail": "ordered_ids required."}, status=400)

        # piece_id is the parent whose children are being reordered
        parent = get_object_or_404(WritingPiece, pk=piece_id)

        try:
            LivingBookService.reorder_siblings(lb, parent, ordered_ids)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


class LivingBookNodeRemoveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk, piece_id):
        lb = get_object_or_404(LivingBook, pk=pk)
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        piece = get_object_or_404(WritingPiece, pk=piece_id)

        try:
            LivingBookService.remove_node(lb, piece, removed_by=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


class LivingBookContextView(APIView):
    """Preceding and following node for Context Flow Mode carousel."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk, piece_id):
        lb = get_object_or_404(LivingBook, pk=pk)
        piece = get_object_or_404(WritingPiece, pk=piece_id)
        prev_p, next_p = LivingBookService.get_context_neighbors(
            lb, piece, for_editor=_for_editor(request, lb)
        )
        return Response({
            "prev": _serialize_context_piece(prev_p),
            "next": _serialize_context_piece(next_p),
        })
