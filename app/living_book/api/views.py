from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
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
    # LB-11: flat trunk fields + sponsor_type / group_slug (LB-23)
    trunk_id = str(lb.trunk_id) if lb.trunk_id else None
    trunk_slug = None
    trunk_title = None
    if lb.trunk_id:
        trunk_slug = getattr(lb.trunk, "slug", None)
        trunk_title = lb.trunk.title or "Untitled"

    group_slug = None
    if lb.sponsor_content_type_id and lb.sponsor_content_type.model == "group":
        group_slug = getattr(lb.sponsor, "slug", None)

    return {
        "id": str(lb.pk),
        "title": lb.title,
        "description": lb.description,
        "status": lb.status,
        "trunk_id": trunk_id,
        "trunk_slug": trunk_slug,
        "trunk_title": trunk_title,
        "sponsor_type": "group" if group_slug else None,
        "group_slug": group_slug,
        "created_by": str(lb.created_by_id) if lb.created_by_id else None,
        "created_at": lb.created_at,
        "updated_at": lb.updated_at,
    }


def _serialize_tree_node(node):
    # LB-12: flat node shape — no nested piece.*
    piece = node["obj"]
    return {
        "id": str(piece.pk),
        "slug": getattr(piece, "slug", None),
        "title": piece.title or "Untitled",
        "depth": node["depth"],
        "position": node["position"],
        "relationship_id": str(node["relationship"].id),
        "is_published": _is_published(piece),
    }


def _serialize_context_piece(piece):
    if piece is None:
        return None
    body = getattr(piece, "body", "") or ""
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
    """True if the requesting user may edit this Living Book (group feature — group-only)."""
    if request.user.is_superuser:
        return True
    if not (lb.sponsor_content_type_id and lb.sponsor_content_type.model == "group"):
        return False
    return _user_is_group_editor(request.user, lb.sponsor)


def _user_is_group_editor(user, group) -> bool:
    """True if user is owner/admin/steward of group."""
    user_ct = ContentType.objects.get_for_model(user.__class__)
    membership = group.memberships.filter(
        member_content_type=user_ct,
        member_object_id=user.pk,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).first()
    if membership is None:
        return False
    return membership.is_owner() or membership.is_admin() or membership.is_steward()


# -------------------------------------------------------------------------
# Views
# -------------------------------------------------------------------------

class LivingBookListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = LivingBook.objects.filter(
            status__in=(LivingBook.STATUS_DRAFT, LivingBook.STATUS_ACTIVE)
        ).select_related("trunk", "created_by", "sponsor_content_type")
        trunk_slug = request.query_params.get("trunk_slug")
        if trunk_slug:
            qs = qs.filter(trunk__slug=trunk_slug)
        return Response([_serialize_living_book(lb) for lb in qs])

    def post(self, request):
        piece_slug = request.data.get("piece_slug")
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "")
        group_slug = request.data.get("group_slug", "").strip() or None

        if not piece_slug:
            return Response({"detail": "piece_slug required."}, status=400)
        if not title:
            return Response({"detail": "title required."}, status=400)
        if not group_slug:
            return Response({"detail": "group_slug required. Living Books are a group feature."}, status=400)

        group = get_object_or_404(Group, slug=group_slug)
        if not _user_is_group_editor(request.user, group):
            return Response({"detail": "Not authorized."}, status=403)

        piece = get_object_or_404(WritingPiece, slug=piece_slug)

        try:
            lb = LivingBookService.promote_to_living_book(
                piece,
                title=title,
                description=description,
                sponsor=group,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(_serialize_living_book(lb), status=201)


class LivingBookDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        return Response(_serialize_living_book(lb))

    def patch(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
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
        # LB-12: return direct array (no envelope)
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        nodes = LivingBookService.get_tree(lb, for_editor=_for_editor(request, lb))
        return Response([_serialize_tree_node(n) for n in nodes])


class LivingBookAccumulatedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        # LB-13: return direct array (no envelope)
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        sections = LivingBookService.get_accumulated_view(lb, for_editor=_for_editor(request, lb))
        return Response(sections)


class LivingBookNodeAddView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
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
        # LB-22: pass group context to create_and_add_node when book is group-sponsored
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        parent_id = request.data.get("parent_id")
        position = request.data.get("position")
        title = request.data.get("title", "")

        parent = None
        if parent_id:
            parent = get_object_or_404(WritingPiece, pk=parent_id)

        group = None
        if lb.sponsor_content_type_id and lb.sponsor_content_type.model == "group":
            group = lb.sponsor

        try:
            piece, rel = LivingBookService.create_and_add_node(
                lb, parent=parent,
                position=int(position) if position is not None else None,
                author=request.user,
                title=title,
                group=group,
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
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        # LB-14: payload key is ordered_piece_ids (was ordered_ids)
        ordered_ids = request.data.get("ordered_piece_ids", [])
        if not ordered_ids:
            return Response({"detail": "ordered_piece_ids required."}, status=400)

        parent = get_object_or_404(WritingPiece, pk=piece_id)

        try:
            LivingBookService.reorder_siblings(lb, parent, ordered_ids)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


class LivingBookRootReorderView(APIView):
    """Reorder top-level nodes (direct children of the LivingBook root)."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        if not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        ordered_ids = request.data.get("ordered_piece_ids", [])
        if not ordered_ids:
            return Response({"detail": "ordered_piece_ids required."}, status=400)

        try:
            LivingBookService.reorder_siblings(lb, lb, ordered_ids)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


class LivingBookNodeRemoveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk, piece_id):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
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
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        piece = get_object_or_404(WritingPiece, pk=piece_id)
        prev_p, next_p = LivingBookService.get_context_neighbors(
            lb, piece, for_editor=_for_editor(request, lb)
        )
        return Response({
            "prev": _serialize_context_piece(prev_p),
            "next": _serialize_context_piece(next_p),
        })
