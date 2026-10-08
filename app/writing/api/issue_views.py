# writing/api/issue_views.py
# ADR-0054 (+ Phase 3 amendment): Issue Board and Publish Cascade

from django.db import transaction
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece, WorkingDocument, Issue, IssuePlacement
from writing.permissions import can_edit_others_group_writing
from writing.publish_service import ensure_published_feed_placement, publish_and_place
from writing.services import WorkingCopyConflict, get_editing_document
from dispatch.access import active_group_ids
from groups.models import Group, GroupMembership
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
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
    issue = get_object_or_404(Issue, id=issue_id)
    if not _can_manage_issue(issue, user):
        raise PermissionDenied("You cannot manage this Issue.")
    return issue


def _can_manage_issue(issue, user):
    user_ct = ContentType.objects.get_for_model(user)
    if issue.sponsor_content_type_id == user_ct.id:
        return str(issue.sponsor_object_id) == str(user.pk)
    group_ct = ContentType.objects.get_for_model(Group)
    if issue.sponsor_content_type_id != group_ct.id:
        return False
    return _can_manage_group(issue.sponsor_object_id, user)


def _can_manage_group(group_id, user):
    if user.is_superuser:
        return True
    user_ct = ContentType.objects.get_for_model(user)
    membership = GroupMembership.objects.filter(
        group_id=group_id,
        member_content_type=user_ct,
        member_object_id=user.pk,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).first()
    return bool(membership and (membership.is_admin() or membership.is_owner()))


def _resolve_sponsor(request):
    source = request.data if request.method == "POST" else request.query_params
    sponsor_type = source.get("sponsor_type", "member")
    if sponsor_type == "member":
        return ContentType.objects.get_for_model(request.user), request.user.pk
    if sponsor_type != "group":
        raise ValidationError({"sponsor_type": "Expected member or group."})
    group_slug = source.get("sponsor_slug")
    if not group_slug:
        raise ValidationError({"sponsor_slug": "Required for group Issues."})
    group = get_object_or_404(Group, slug=group_slug)
    group_ct = ContentType.objects.get_for_model(Group)
    if not _can_manage_group(group.pk, request.user):
        raise PermissionDenied("You cannot manage this group's Issues.")
    return group_ct, group.pk


def _reviewed_piece(request, pk, *, require_title=False):
    piece = get_object_or_404(WritingPiece.objects.select_for_update(), id=pk)
    if piece.author_id != request.user.id and not can_edit_others_group_writing(request.user, piece):
        raise PermissionDenied("You cannot review this piece.")
    if piece.status == "published":
        raise ValidationError("Published pieces cannot be reviewed as drafts.")
    try:
        draft = get_editing_document(piece, request.user, create=True, lock=True)
    except WorkingCopyConflict as exc:
        return piece, None, Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    expected = request.data.get("expected_auto_save_count")
    if expected is None or str(draft.auto_save_count) != str(expected):
        return piece, None, Response(
            {"detail": "Draft changed or its revision is missing. Reload before approving."},
            status=status.HTTP_409_CONFLICT,
        )
    if require_title and not draft.title.strip():
        return piece, draft, Response(
            {"detail": "Add a title before signing off."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(draft.title) > WritingPiece._meta.get_field("title").max_length:
        return piece, draft, Response(
            {"detail": "Draft title is too long for a WritingPiece."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if draft.body_json != piece.body_json or draft.title != piece.title:
        piece.title = draft.title
        piece.body_json = draft.body_json
        piece.spellcheck_clean = False
        piece.signed_off = False
        piece.signed_off_by = None
        piece.save(update_fields=[
            "title", "body_json", "is_empty", "reading_time", "slug",
            "slug_history", "spellcheck_clean", "signed_off", "signed_off_by",
            "updated_at",
        ])
    return piece, draft, None


# ---------------------------------------------------------------------------
# Views — Issues
# ---------------------------------------------------------------------------

class IssueListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ct, obj_id = _resolve_sponsor(request)
        issues = Issue.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        ).prefetch_related("placements__piece").order_by("-updated_at")
        return Response(IssueListSerializer(issues, many=True).data)

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"title": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
        ct, obj_id = _resolve_sponsor(request)
        issue = Issue.objects.create(
            title=title,
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        )
        return Response(IssueSerializer(issue).data, status=status.HTTP_201_CREATED)


class IssueGroupingView(APIView):
    """Issue order and membership for pieces visible in a Writing work area."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sponsor_type = request.query_params.get("sponsor_type")
        sponsor_slug = request.query_params.get("sponsor_slug")
        group_ct = ContentType.objects.get_for_model(Group)
        user_ct = ContentType.objects.get_for_model(request.user)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)

        if sponsor_type == "group":
            group = get_object_or_404(Group, slug=sponsor_slug)
            if not request.user.is_superuser and not active_group_ids(request.user).filter(group_id=group.pk).exists():
                raise PermissionDenied("You cannot view this group's Issues.")
            placements = IssuePlacement.objects.filter(
                issue__sponsor_content_type=group_ct,
                issue__sponsor_object_id=group.pk,
                piece__sponsor_content_type=group_ct,
                piece__sponsor_object_id=group.pk,
            )
            if not _can_manage_group(group.pk, request.user):
                placements = placements.filter(issue__status="published")
        elif sponsor_type == "member":
            if sponsor_slug != request.user.username:
                raise PermissionDenied("You cannot view another member's Issues.")
            placements = IssuePlacement.objects.filter(
                Q(issue__sponsor_content_type=user_ct, issue__sponsor_object_id=request.user.pk)
                | Q(issue__sponsor_content_type=group_ct,
                    issue__sponsor_object_id__in=active_group_ids(request.user)),
            )
        else:
            return Response({"detail": "Expected a group or member sponsor."}, status=status.HTTP_400_BAD_REQUEST)

        placements = list(placements.select_related("issue", "piece").order_by(
            "-issue__updated_at", "issue_id", "order_index", "added_at", "pk"
        ))
        if sponsor_type == "member":
            manageable_groups = {}
            visible_placements = []
            for placement in placements:
                issue = placement.issue
                if issue.sponsor_content_type_id == group_ct.id and issue.status != "published":
                    group_id = issue.sponsor_object_id
                    if group_id not in manageable_groups:
                        manageable_groups[group_id] = _can_manage_group(group_id, request.user)
                    if not manageable_groups[group_id]:
                        continue
                visible_placements.append(placement)
            placements = visible_placements
        if not placements:
            return Response([])

        candidate_ids = {placement.piece_id for placement in placements}
        if sponsor_type == "group":
            published_ids = {placement.piece_id for placement in placements if placement.piece.status == "published"}
            visible_published = {
                placement.source_object_id
                for placement in ContentPlacement.objects.filter(
                    target_content_type=group_ct,
                    target_object_id=group.pk,
                    source_content_type=piece_ct,
                    source_object_id__in=published_ids,
                    channel="feed",
                )
                if can_view_placement(placement, request.user)
            }
            draft_ids = set(WorkingDocument.objects.filter(
                piece_id__in=candidate_ids,
                piece__status="draft",
            ).filter(Q(user=request.user) | Q(dispatch_content__collaborators=request.user))
                .values_list("piece_id", flat=True).distinct())
            visible_ids = visible_published | draft_ids
        else:
            visible_published = set(WritingPiece.objects.filter(
                pk__in=candidate_ids, author=request.user, status="published", is_empty=False,
            ).values_list("pk", flat=True))
            draft_ids = set(WorkingDocument.objects.filter(
                piece_id__in=candidate_ids,
                piece__status="draft",
                piece__sponsor_content_type=user_ct,
                piece__sponsor_object_id=request.user.pk,
            ).filter(Q(user=request.user) | Q(dispatch_content__collaborators=request.user))
                .values_list("piece_id", flat=True).distinct())
            visible_ids = visible_published | draft_ids

        group_ids = {
            placement.issue.sponsor_object_id for placement in placements
            if placement.piece_id in visible_ids and placement.issue.sponsor_content_type_id == group_ct.id
        }
        group_names = dict(Group.objects.filter(pk__in=group_ids).values_list("pk", "title"))
        groups = {}
        for placement in placements:
            if placement.piece_id not in visible_ids:
                continue
            issue = placement.issue
            key = str(issue.pk)
            if key not in groups:
                groups[key] = {
                    "id": key,
                    "title": issue.title,
                    "designation": issue.designation,
                    "status": issue.status,
                    "sponsor_label": group_names.get(issue.sponsor_object_id, "Group")
                    if issue.sponsor_content_type_id == group_ct.id else "Personal",
                    "piece_ids": [],
                }
            groups[key]["piece_ids"].append(str(placement.piece_id))
        return Response(list(groups.values()))


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

    @transaction.atomic
    def post(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        issue = Issue.objects.select_for_update().get(pk=issue.pk)

        if issue.status == "published":
            return Response({"detail": "Issue is already published."}, status=status.HTTP_400_BAD_REQUEST)

        placements = list(issue.placements.order_by("order_index"))
        if not placements:
            return Response({"detail": "Cannot publish an empty Issue."}, status=status.HTTP_400_BAD_REQUEST)

        pieces = {
            piece.pk: piece for piece in WritingPiece.objects.select_for_update().filter(
                pk__in=[placement.piece_id for placement in placements]
            ).order_by("pk")
        }
        not_ready = []
        for placement in placements:
            piece = pieces[placement.piece_id]
            try:
                draft = get_editing_document(piece, piece.author, lock=True)
            except WorkingCopyConflict:
                not_ready.append(piece.title or str(piece.pk))
                continue
            if (
                (draft and (draft.body_json != piece.body_json or draft.title != piece.title))
                or not piece.title.strip()
                or not (piece.spellcheck_clean and piece.signed_off)
            ):
                not_ready.append(piece.title or str(piece.pk))
        if not_ready:
            return Response(
                {"detail": "All Docs must match their approved draft, have spelling reviewed, and be signed off before publishing.",
                 "not_ready": not_ready},
                status=status.HTTP_400_BAD_REQUEST,
            )

        group_ct = ContentType.objects.get_for_model(Group)
        if issue.sponsor_content_type_id == group_ct.id:
            destination = get_object_or_404(Group, pk=issue.sponsor_object_id)
            destinations = {"groups": [destination.slug]}
            visibility = "members" if destination.visibility == "private" else destination.visibility
        else:
            destination = request.user
            destinations = {"personal": True}
            visibility = "public"

        for placement in placements:
            piece = pieces[placement.piece_id]
            if piece.status == "published":
                ensure_published_feed_placement(piece, request.user, destination, visibility=visibility)
            else:
                result = publish_and_place(piece, request.user, {
                    "destinations": destinations,
                    "placement_options": {"visibility": visibility},
                })
                if not result["placements"]:
                    raise PermissionDenied("You cannot publish to this Issue's sponsor.")

        now = timezone.now()
        issue.status = "published"
        issue.published_at = now
        issue.save(update_fields=["status", "published_at", "updated_at"])

        return Response(IssueSerializer(issue).data)


class IssueUnpublishView(APIView):
    """Return an Issue to draft, optionally returning all of its pieces to drafts."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, issue_id):
        issue = _get_issue_for_user(issue_id, request.user)
        issue = Issue.objects.select_for_update().get(pk=issue.pk)
        cascade = request.data.get("cascade") is True

        if not cascade and issue.status != "published":
            return Response({"detail": "Issue is already a draft."}, status=status.HTTP_400_BAD_REQUEST)

        if cascade:
            pieces = list(WritingPiece.objects.select_for_update().filter(
                pk__in=issue.placements.values("piece_id")
            ).order_by("pk"))
            shared = list(IssuePlacement.objects.filter(
                piece_id__in=[piece.pk for piece in pieces], issue__status="published"
            ).exclude(issue=issue).select_related("piece").values_list("piece__title", flat=True).distinct())
            if shared:
                return Response(
                    {"detail": "Some pieces belong to another published Issue.", "shared_pieces": shared},
                    status=status.HTTP_409_CONFLICT,
                )
            for piece in pieces:
                if piece.status == "published":
                    piece.unpublish()

        issue.status = "draft"
        issue.published_at = None
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

        if (piece.sponsor_content_type_id != issue.sponsor_content_type_id
                or str(piece.sponsor_object_id) != str(issue.sponsor_object_id)):
            return Response({"detail": "Piece and Issue must have the same sponsor."}, status=status.HTTP_403_FORBIDDEN)

        before_piece_id = request.data.get("before_piece_id")
        with transaction.atomic():
            issue = Issue.objects.select_for_update().get(pk=issue.pk)
            placements = list(issue.placements.order_by("order_index", "added_at", "id"))
            if any(existing.piece_id == piece.id for existing in placements):
                return Response({"detail": "Piece is already in this Issue."}, status=status.HTTP_400_BAD_REQUEST)

            insert_at = len(placements)
            if before_piece_id is not None:
                insert_at = next(
                    (index for index, existing in enumerate(placements) if str(existing.piece_id) == str(before_piece_id)),
                    -1,
                )
                if insert_at < 0:
                    return Response({"before_piece_id": "Piece is not in this Issue."}, status=status.HTTP_400_BAD_REQUEST)

            placement = IssuePlacement.objects.create(issue=issue, piece=piece, order_index=len(placements))
            placements.insert(insert_at, placement)
            for index, existing in enumerate(placements):
                existing.order_index = index
            IssuePlacement.objects.bulk_update(placements, ["order_index"])

            # Adding a piece reverts a published Issue to draft.
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

        is_editor = request.user.is_superuser or _can_manage_issue(issue, request.user)
        group_ct = ContentType.objects.get_for_model(Group)
        if (issue.sponsor_content_type_id == group_ct.pk
                and issue.status != "published" and not is_editor):
            return Response(status=status.HTTP_404_NOT_FOUND)

        data = IssueReadSerializer(issue).data
        if not is_editor:
            data["placements"] = [p for p in data["placements"] if p["status"] == "published"]
        data["is_editor"] = is_editor
        return Response(data)


# ---------------------------------------------------------------------------
# Views — Piece sign-off toggle (D10)
# ---------------------------------------------------------------------------

class WritingPieceSignOffView(APIView):
    """Approve the exact draft revision reviewed by its author or group steward."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        piece, draft, conflict = _reviewed_piece(request, pk, require_title=True)
        if conflict is not None:
            return conflict
        piece.signed_off = True
        piece.signed_off_by = request.user
        piece.save(update_fields=["signed_off", "signed_off_by", "updated_at"])
        return Response({"signed_off": True, "signed_off_by": str(request.user.pk), "piece_id": str(piece.id), "auto_save_count": draft.auto_save_count})


class WritingPieceSpellingReviewView(APIView):
    """Manual spelling review of the exact saved draft revision."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        piece, draft, conflict = _reviewed_piece(request, pk)
        if conflict is not None:
            return conflict
        piece.spellcheck_clean = True
        piece.save(update_fields=["spellcheck_clean", "updated_at"])
        return Response({"spellcheck_clean": True, "piece_id": str(piece.id), "auto_save_count": draft.auto_save_count})
