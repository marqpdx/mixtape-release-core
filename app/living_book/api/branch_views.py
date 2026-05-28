from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..branch_service import BranchService, LeafClusterService, _is_dispatch_collaborator
from ..models import Branch, LeafCluster, LivingBook
from .views import _for_editor


# ─── Serializers ────────────────────────────────────────────────────────────

def _serialize_branch(branch: Branch) -> dict:
    return {
        "id": str(branch.pk),
        "living_book_id": str(branch.living_book_id),
        "anchor_node_id": str(branch.anchor_node_id),
        "prompt_text": branch.prompt_text,
        "due_date": branch.due_date.isoformat() if branch.due_date else None,
        "is_detached": branch.is_detached,
        "created_by": str(branch.created_by_id) if branch.created_by_id else None,
        "created_at": branch.created_at,
        "updated_at": branch.updated_at,
    }


def _serialize_leaf_cluster(lc: LeafCluster) -> dict:
    piece = lc.piece
    return {
        "id": str(lc.pk),
        "branch_id": str(lc.branch_id),
        "piece": {
            "id": str(piece.pk),
            "slug": getattr(piece, "slug", None),
            "title": piece.title or "Untitled",
            "is_published": str(getattr(piece, "status", "")).lower() in ("published", "public"),
            "author_username": getattr(piece.author, "username", None) if piece.author_id else None,
        },
        "media_type": lc.media_type,
        "created_by": str(lc.created_by_id) if lc.created_by_id else None,
        "created_at": lc.created_at,
    }


# ─── Branch views ────────────────────────────────────────────────────────────

class BranchListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)
        branches = lb.branches.select_related("created_by").order_by("created_at")
        return Response([_serialize_branch(b) for b in branches])

    def post(self, request, pk):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)

        anchor_node_id = request.data.get("anchor_node_id")
        if not anchor_node_id:
            return Response({"detail": "anchor_node_id required."}, status=400)

        try:
            branch = BranchService.create_branch(
                lb,
                anchor_node_id,
                created_by=request.user,
                prompt_text=request.data.get("prompt_text"),
                due_date=request.data.get("due_date"),
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response(_serialize_branch(branch), status=201)


class BranchDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_lb_and_branch(self, pk, branch_id):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        branch = get_object_or_404(Branch, pk=branch_id, living_book=lb)
        return lb, branch

    def patch(self, request, pk, branch_id):
        lb, branch = self._get_lb_and_branch(pk, branch_id)
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)

        kwargs = {}
        if "prompt_text" in request.data:
            kwargs["prompt_text"] = request.data["prompt_text"]
        if "due_date" in request.data:
            kwargs["due_date"] = request.data["due_date"]
        if "is_detached" in request.data:
            kwargs["is_detached"] = request.data["is_detached"]

        branch = BranchService.update_branch(branch, **kwargs)
        return Response(_serialize_branch(branch))

    def delete(self, request, pk, branch_id):
        lb, branch = self._get_lb_and_branch(pk, branch_id)
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)

        try:
            BranchService.delete_branch(branch)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


class BranchSendInvitationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, branch_id):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        branch = get_object_or_404(Branch, pk=branch_id, living_book=lb)

        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)

        try:
            BranchService.send_invitation(branch, sent_by=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(status=204)


# ─── LeafCluster views ───────────────────────────────────────────────────────

class LeafClusterListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_lb_and_branch(self, pk, branch_id):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        branch = get_object_or_404(Branch, pk=branch_id, living_book=lb)
        return lb, branch

    def get(self, request, pk, branch_id):
        lb, branch = self._get_lb_and_branch(pk, branch_id)
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)
        leaf_clusters = branch.leaf_clusters.select_related(
            "piece", "piece__author", "created_by"
        ).order_by("created_at")
        return Response([_serialize_leaf_cluster(lc) for lc in leaf_clusters])

    def post(self, request, pk, branch_id):
        lb, branch = self._get_lb_and_branch(pk, branch_id)
        if not _is_dispatch_collaborator(request.user, lb):
            return Response({"detail": "Not authorized."}, status=403)

        piece_slug = request.data.get("piece_slug")
        if not piece_slug:
            return Response({"detail": "piece_slug required."}, status=400)

        media_type = request.data.get("media_type", LeafCluster.MEDIA_TEXT)

        try:
            lc = LeafClusterService.attach_piece(
                branch,
                piece_slug,
                created_by=request.user,
                media_type=media_type,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(_serialize_leaf_cluster(lc), status=201)


class LeafClusterDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk, branch_id, lc_id):
        lb = get_object_or_404(
            LivingBook.objects.select_related("trunk", "sponsor_content_type"), pk=pk
        )
        branch = get_object_or_404(Branch, pk=branch_id, living_book=lb)
        lc = get_object_or_404(
            LeafCluster.objects.select_related("piece", "piece__author"), pk=lc_id, branch=branch
        )

        # Only the leaf-cluster author or a group editor may detach
        is_author = lc.created_by_id == request.user.pk
        if not is_author and not _for_editor(request, lb):
            return Response({"detail": "Not authorized."}, status=403)

        LeafClusterService.detach_piece(lc)
        return Response(status=204)
