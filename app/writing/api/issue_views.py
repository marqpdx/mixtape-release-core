# writing/api/issue_views.py
# ADR-0054 (+ Phase 3 amendment): Issue Board and Publish Cascade

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece, Issue, IssuePlacement
from writing.api.serializers import (
    IssuePlacementSerializer,
    IssueSerializer,
    IssueListSerializer,
    IssueReadSerializer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_issue_for_user(issue_id, user):
    """Fetch an Issue owned by the given user (member sponsor)."""
    from django.contrib.contenttypes.models import ContentType
    user_ct = ContentType.objects.get_for_model(user)
    return get_object_or_404(
        Issue,
        id=issue_id,
        sponsor_content_type=user_ct,
        sponsor_object_id=str(user.pk),
    )


def _get_sponsor_ct_and_id(user):
    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(user)
    return ct, str(user.pk)


# ---------------------------------------------------------------------------
# Views — Issues
# ---------------------------------------------------------------------------

class IssueListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ct, obj_id = _get_sponsor_ct_and_id(request.user)
        issues = Issue.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        ).order_by("-updated_at")
        return Response(IssueListSerializer(issues, many=True).data)

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"title": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
        ct, obj_id = _get_sponsor_ct_and_id(request.user)
        issue = Issue.objects.create(
            title=title,
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        )
        return Response(IssueSerializer(issue).data, status=status.HTTP_201_CREATED)


class IssueDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        return Response(IssueSerializer(issue).data)

    def patch(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        title = request.data.get("title")
        if title is not None:
            issue.title = title.strip()
        designation = request.data.get("designation")
        if designation is not None:
            issue.designation = designation.strip() or None
        description = request.data.get("description")
        if description is not None:
            issue.description = description
        issue.save()
        return Response(IssueSerializer(issue).data)

    def delete(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        issue.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssuePublishView(APIView):
    """
    Gate-up check + cascade-down publish.
    All member Docs must be Green (spellcheck_clean + signed_off) before publish.
    Publishing atomically sets all member Docs to published status.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)

        if issue.status == "published":
            return Response({"detail": "Issue is already published."}, status=status.HTTP_400_BAD_REQUEST)

        placements = list(issue.placements.select_related("piece").order_by("order_index"))
        if not placements:
            return Response({"detail": "Cannot publish an empty Issue."}, status=status.HTTP_400_BAD_REQUEST)

        not_ready = [p.piece.title or str(p.piece.id) for p in placements
                     if not (p.piece.spellcheck_clean and p.piece.signed_off)]
        if not_ready:
            return Response(
                {"detail": "All Docs must be spellcheck-clean and signed off before publishing.",
                 "not_ready": not_ready},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            now = timezone.now()
            pieces = [p.piece for p in placements]
            for piece in pieces:
                if piece.status != "published":
                    piece.status = "published"
                    piece.published_at = now
                    piece.save(update_fields=["status", "published_at", "updated_at"])
            issue.status = "published"
            issue.published_at = now
            issue.save(update_fields=["status", "published_at", "updated_at"])

        return Response(IssueSerializer(issue).data)


# ---------------------------------------------------------------------------
# Views — Issue Placements
# ---------------------------------------------------------------------------

class IssuePlacementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        placements = issue.placements.select_related("piece").order_by("order_index")
        return Response(IssuePlacementSerializer(placements, many=True).data)

    def post(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        piece_id = request.data.get("piece_id")
        if not piece_id:
            return Response({"piece_id": "Required."}, status=status.HTTP_400_BAD_REQUEST)

        piece = get_object_or_404(WritingPiece, id=piece_id)

        # Verify the piece belongs to the same sponsor
        from django.contrib.contenttypes.models import ContentType
        user_ct = ContentType.objects.get_for_model(request.user)
        if piece.sponsor_content_type != user_ct or str(piece.sponsor_object_id) != str(request.user.pk):
            return Response({"detail": "Piece does not belong to your writing."}, status=status.HTTP_403_FORBIDDEN)

        if IssuePlacement.objects.filter(issue=issue, piece=piece).exists():
            return Response({"detail": "Piece is already in this Issue."}, status=status.HTTP_400_BAD_REQUEST)

        max_index = issue.placements.aggregate(m=Max("order_index"))["m"]
        order_index = (max_index or -1) + 1

        placement = IssuePlacement.objects.create(issue=issue, piece=piece, order_index=order_index)

        # Adding a piece reverts a published Issue to draft
        if issue.status == "published":
            issue.status = "draft"
            issue.published_at = None
            issue.save(update_fields=["status", "published_at", "updated_at"])

        return Response(IssuePlacementSerializer(placement).data, status=status.HTTP_201_CREATED)


class IssuePlacementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, issue_id, piece_id):
        issue = _get_issue_for_user(issue_id, request.user)
        placement = get_object_or_404(IssuePlacement, issue=issue, piece_id=piece_id)
        placement.delete()

        # Removing a piece reverts a published Issue to draft
        if issue.status == "published":
            issue.status = "draft"
            issue.published_at = None
            issue.save(update_fields=["status", "published_at", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, issue_id, piece_id):
        issue = _get_issue_for_user(issue_id, request.user)
        placement = get_object_or_404(IssuePlacement, issue=issue, piece_id=piece_id)
        is_lead = request.data.get("is_lead")
        if is_lead is not None:
            is_lead = bool(is_lead)
            if is_lead:
                # Application-level constraint: at most one lead per Issue.
                issue.placements.exclude(pk=placement.pk).filter(is_lead=True).update(is_lead=False)
            placement.is_lead = is_lead
            placement.save(update_fields=["is_lead"])
        return Response(IssuePlacementSerializer(placement).data)


class IssuePlacementsReorderView(APIView):
    """
    PATCH with {"piece_ids": [...]} in new order.
    Reordering a published Issue reverts it to draft (D6).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        piece_ids = request.data.get("piece_ids")
        if not isinstance(piece_ids, list):
            return Response({"piece_ids": "Must be a list of piece UUIDs."}, status=status.HTTP_400_BAD_REQUEST)

        placements = {str(p.piece_id): p for p in issue.placements.all()}

        if set(piece_ids) != set(placements.keys()):
            return Response(
                {"detail": "piece_ids must contain exactly the current member piece IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        was_published = issue.status == "published"

        with transaction.atomic():
            for idx, pid in enumerate(piece_ids):
                p = placements[str(pid)]
                p.order_index = idx
                p.save(update_fields=["order_index"])

            if was_published:
                issue.status = "draft"
                issue.published_at = None
                issue.save(update_fields=["status", "published_at", "updated_at"])

        issue.refresh_from_db()
        return Response(IssueSerializer(issue).data)


# ---------------------------------------------------------------------------
# Views — Continuous Read (Phase 3 amendment P3-4)
# ---------------------------------------------------------------------------

class IssueReadView(APIView):
    """
    GET /api/writing/issues/{issue_id}/read

    Full-body ordered placements for the Continuous Read view, generalized
    from Living Books' Accumulated Read (LB-9). Editors (sponsor owner or
    superuser) see every placement including drafts; everyone else sees only
    published pieces — same split as Living Books' visibleNodes filter.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, issue_id):
        issue = get_object_or_404(Issue, id=issue_id)

        from django.contrib.contenttypes.models import ContentType
        user_ct = ContentType.objects.get_for_model(request.user)
        is_owner = (
            issue.sponsor_content_type_id == user_ct.pk
            and str(issue.sponsor_object_id) == str(request.user.pk)
        )
        is_editor = is_owner or request.user.is_superuser

        data = IssueReadSerializer(issue).data
        if not is_editor:
            data["placements"] = [p for p in data["placements"] if p["status"] == "published"]
        data["is_editor"] = is_editor
        return Response(data)


# ---------------------------------------------------------------------------
# Views — Piece sign-off toggle (D10)
# ---------------------------------------------------------------------------

class WritingPieceSignOffView(APIView):
    """POST to set signed_off=True on a piece. Cleared automatically on next body edit."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        piece = get_object_or_404(WritingPiece, id=pk)
        if piece.author != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        piece.signed_off = True
        piece.save(update_fields=["signed_off", "updated_at"])
        return Response({"signed_off": True, "piece_id": str(piece.id)})
