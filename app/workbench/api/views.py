# workbench/api/views.py

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from workbench.models import WorkingItem, WorkingItemMembership, WorkingItemStatus
from workbench.api.serializers import (
    AutosaveSerializer,
    MembershipReorderSerializer,
    WorkingItemListSerializer,
    WorkingItemMembershipSerializer,
    WorkingItemSerializer,
)

logger = logging.getLogger(__name__)


def _get_group(slug):
    return get_object_or_404(Group, slug=slug)


def _superuser_required(request):
    """v0: Workbench is superuser-only. Returns True if allowed."""
    return request.user.is_superuser


# ---------------------------------------------------------------------------
# WorkingItem list + create
# ---------------------------------------------------------------------------

class WorkingItemListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)

        qs = WorkingItem.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        ).select_related("author")

        # Status filter — default: exclude promoted/archived
        status_param = request.query_params.get("status")
        if status_param:
            requested = [s.strip() for s in status_param.split(",")]
            qs = qs.filter(status__in=requested)
        else:
            qs = qs.exclude(status__in=[WorkingItemStatus.PROMOTED, WorkingItemStatus.ARCHIVED])

        serializer = WorkingItemListSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)

        title = request.data.get("title", "").strip()
        pieces_data = request.data.get("pieces", [])  # [{content_type_id, object_id, position}]

        working_item = WorkingItem(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            author=request.user,
            submitted_by=request.user,
            title=title,
            status=WorkingItemStatus.ASSEMBLING,
        )
        working_item.save()

        # Stitch memberships + body_json from pieces
        body_content = []
        for piece_data in sorted(pieces_data, key=lambda p: p.get("position", 0)):
            try:
                piece_ct = ContentType.objects.get(pk=piece_data["content_type_id"])
                piece_obj = piece_ct.get_object_for_this_type(pk=piece_data["object_id"])
                snapshot = _extract_snapshot(piece_obj)
            except Exception:
                logger.exception(
                    "workbench_create_piece_error content_type_id=%s object_id=%s",
                    piece_data.get("content_type_id"),
                    piece_data.get("object_id"),
                )
                continue

            WorkingItemMembership.objects.create(
                working_item=working_item,
                piece_content_type=piece_ct,
                piece_object_id=piece_data["object_id"],
                content_snapshot=snapshot,
                position=piece_data.get("position", 0),
            )
            if snapshot:
                body_content.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": snapshot}],
                })

        if body_content:
            working_item.body_json = {"type": "doc", "content": body_content}
            working_item.save(update_fields=["body_json", "updated_at"])

        logger.info("workbench_item_created id=%s group=%s pieces=%d", working_item.pk, slug, len(pieces_data))
        return Response(WorkingItemSerializer(working_item).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# WorkingItem detail (retrieve, update, delete)
# ---------------------------------------------------------------------------

class WorkingItemDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, slug, item_id):
        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            WorkingItem,
            id=item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        item = self._get_item(slug, item_id)
        return Response(WorkingItemSerializer(item).data)

    def patch(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        item = self._get_item(slug, item_id)

        if item.status == WorkingItemStatus.PROMOTED:
            return Response(
                {"detail": "Promoted WorkingItems are immutable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed_fields = {"title", "summary", "status", "target_writing_kind", "promotion_gates"}
        update_fields = []

        for field in allowed_fields:
            if field in request.data:
                setattr(item, field, request.data[field])
                update_fields.append(field)

        if not update_fields:
            return Response({"detail": "No updatable fields provided."}, status=status.HTTP_400_BAD_REQUEST)

        update_fields.append("updated_at")
        item.save(update_fields=update_fields)
        return Response(WorkingItemSerializer(item).data)

    def delete(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        item = self._get_item(slug, item_id)

        if item.status == WorkingItemStatus.PROMOTED:
            return Response(
                {"detail": "Cannot delete a promoted WorkingItem — it is a provenance record."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item.deleted_at = timezone.now()
        item.status = WorkingItemStatus.ARCHIVED
        item.save(update_fields=["deleted_at", "status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Autosave
# ---------------------------------------------------------------------------

class WorkingItemAutosaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)
        item = get_object_or_404(
            WorkingItem,
            id=item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

        if item.status == WorkingItemStatus.PROMOTED:
            return Response(
                {"detail": "Promoted WorkingItems cannot be autosaved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AutosaveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        update_fields = ["last_saved_at", "auto_save_count", "updated_at"]

        if "body_json" in serializer.validated_data:
            item.body_json = serializer.validated_data["body_json"]
            update_fields.append("body_json")

            # Mark fork lock on first body edit
            if (
                serializer.validated_data.get("mark_body_editing_started", True)
                and not item.body_editing_started
            ):
                item.body_editing_started = True
                update_fields.append("body_editing_started")

            # Reset spellcheck on body change
            if item.spellcheck_passed:
                item.spellcheck_passed = False
                update_fields.append("spellcheck_passed")

        if "title" in serializer.validated_data:
            item.title = serializer.validated_data["title"]
            update_fields.append("title")

        item.last_saved_at = timezone.now()
        item.auto_save_count = item.auto_save_count + 1

        item.save(update_fields=update_fields)

        return Response({
            "id": str(item.id),
            "last_saved_at": item.last_saved_at,
            "auto_save_count": item.auto_save_count,
            "body_editing_started": item.body_editing_started,
            "spellcheck_passed": item.spellcheck_passed,
        })


# ---------------------------------------------------------------------------
# Membership management (add/remove Pieces from a WorkingItem)
# ---------------------------------------------------------------------------

class WorkingItemMembershipView(APIView):
    """
    POST  — add a Piece to a WorkingItem (appends snapshot to body_json)
    DELETE — remove a membership (only if body_editing_started is False)
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, slug, item_id):
        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            WorkingItem,
            id=item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def post(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        item = self._get_item(slug, item_id)

        content_type_id = request.data.get("content_type_id")
        object_id = request.data.get("object_id")

        if not content_type_id or not object_id:
            return Response(
                {"detail": "content_type_id and object_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            piece_ct = ContentType.objects.get(pk=content_type_id)
            piece_obj = piece_ct.get_object_for_this_type(pk=object_id)
        except Exception:
            return Response({"detail": "Piece not found."}, status=status.HTTP_404_NOT_FOUND)

        # Circular reference guard for WorkingItem nesting
        if piece_ct.model == "workingitem" and str(piece_obj.pk) == str(item.pk):
            return Response(
                {"detail": "A WorkingItem cannot be a member of itself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_position = item.memberships.count()
        snapshot = _extract_snapshot(piece_obj)

        membership, created = WorkingItemMembership.objects.get_or_create(
            working_item=item,
            piece_content_type=piece_ct,
            piece_object_id=object_id,
            defaults={"content_snapshot": snapshot, "position": next_position},
        )

        if not created:
            return Response(
                {"detail": "This Piece is already in the WorkingItem."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Append snapshot to body_json non-destructively
        if snapshot:
            doc = item.body_json or {"type": "doc", "content": []}
            doc.setdefault("content", [])
            doc["content"].append({
                "type": "paragraph",
                "content": [{"type": "text", "text": snapshot}],
            })
            item.body_json = doc
            item.save(update_fields=["body_json", "updated_at"])

        return Response(WorkingItemMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    def delete(self, request, slug, item_id, membership_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        item = self._get_item(slug, item_id)

        if item.body_editing_started:
            return Response(
                {"detail": "Cannot remove Pieces after body editing has begun."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership = get_object_or_404(WorkingItemMembership, id=membership_id, working_item=item)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkingItemMembershipReorderView(APIView):
    """
    POST — reorder memberships for a WorkingItem before body editing begins.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, slug, item_id):
        group = _get_group(slug)
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            WorkingItem,
            id=item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def post(self, request, slug, item_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        item = self._get_item(slug, item_id)

        if item.status == WorkingItemStatus.PROMOTED:
            return Response(
                {"detail": "Promoted WorkingItems are immutable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MembershipReorderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        membership_ids = [str(value) for value in serializer.validated_data["membership_ids"]]
        memberships = list(item.memberships.all())
        existing_ids = [str(m.id) for m in memberships]

        if len(membership_ids) != len(set(membership_ids)):
            return Response(
                {"detail": "membership_ids must not contain duplicates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if set(membership_ids) != set(existing_ids):
            return Response(
                {"detail": "membership_ids must exactly match the WorkingItem memberships."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership_map = {str(m.id): m for m in memberships}

        with transaction.atomic():
            for position, membership_id in enumerate(membership_ids):
                membership = membership_map[membership_id]
                if membership.position != position:
                    membership.position = position
                    membership.save(update_fields=["position"])

        refreshed = item.memberships.all()
        return Response({
            "memberships": WorkingItemMembershipSerializer(refreshed, many=True).data
        })


# ---------------------------------------------------------------------------
# Snapshot extractor registry
# ---------------------------------------------------------------------------

def _extract_snapshot(piece_obj) -> str:
    """
    Registry-pattern snapshot extractor.
    Returns plain text content from a Piece object.
    """
    model_name = piece_obj.__class__.__name__.lower()

    extractors = {
        "seed": lambda o: getattr(o, "transcript_text", None) or getattr(o, "body_text", "") or "",
        "leaf": lambda o: getattr(o, "body_text", "") or "",
        "milldraft": lambda o: getattr(o, "grist_body", "") or "",
        "feedbackitem": lambda o: getattr(o, "message", "") or getattr(o, "body", "") or "",
        "workingitem": lambda o: getattr(o, "body", "") or "",
        "workingdocument": lambda o: _prosemirror_to_text(getattr(o, "body_json", {})),
    }

    extractor = extractors.get(model_name)
    if extractor:
        try:
            return extractor(piece_obj)
        except Exception:
            logger.exception("snapshot_extract_failed model=%s pk=%s", model_name, piece_obj.pk)

    return ""


def _prosemirror_to_text(body_json: dict) -> str:
    """Flatten a ProseMirror doc to plain text for snapshot purposes."""
    if not body_json:
        return ""
    parts = []
    for node in body_json.get("content", []):
        for child in node.get("content", []):
            if child.get("type") == "text":
                parts.append(child.get("text", ""))
    return " ".join(parts)
