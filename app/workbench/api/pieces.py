# workbench/api/pieces.py
#
# Unified Piece API — server-side aggregation of all Lane 1 raw content types.
# Returns a normalized Piece shape spanning Seeds, Leaves, MillDrafts,
# FeedbackItems, and WorkingDocuments.

import logging
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from workbench.models import WorkingItem, WorkingItemMembership

logger = logging.getLogger(__name__)

_EXCERPT_LENGTH = 200


# ---------------------------------------------------------------------------
# Normalised Piece shape
# ---------------------------------------------------------------------------

def _make_piece(
    obj,
    type_label: str,
    content_type_id: int,
    title: str,
    excerpt: str,
    author_display: str,
    sponsor_id,
    obj_status: str,
    tags: list,
    created_at: datetime,
    updated_at: datetime,
    working_item_references: list,
) -> dict:
    return {
        "id": str(obj.pk),
        "content_type_id": content_type_id,
        "type_label": type_label,
        "title": title,
        "excerpt": excerpt[:_EXCERPT_LENGTH] if excerpt else "",
        "author": author_display,
        "sponsor_id": str(sponsor_id) if sponsor_id else None,
        "status": obj_status,
        "tags": tags,
        "created_at": created_at,
        "updated_at": updated_at,
        "working_item_references": working_item_references,
    }


# ---------------------------------------------------------------------------
# Working-item reference lookup (batch)
# ---------------------------------------------------------------------------

def _build_wi_reference_map(content_type_id: int, object_ids: list) -> dict:
    """
    Returns {str(object_id): [{id, title}, ...]} for all memberships
    matching the given content_type_id + object_ids.
    """
    memberships = (
        WorkingItemMembership.objects
        .filter(
            piece_content_type_id=content_type_id,
            piece_object_id__in=object_ids,
        )
        .select_related("working_item")
    )
    result = {}
    for m in memberships:
        key = str(m.piece_object_id)
        result.setdefault(key, []).append({
            "id": str(m.working_item_id),
            "title": m.working_item.title or "Untitled",
        })
    return result


# ---------------------------------------------------------------------------
# Per-type extractors
# ---------------------------------------------------------------------------

def _normalise_seeds(qs, ct_id) -> list:
    ids = [o.pk for o in qs]
    wi_map = _build_wi_reference_map(ct_id, ids)
    pieces = []
    for obj in qs:
        body = obj.transcript_text or obj.body_text or ""
        pieces.append(_make_piece(
            obj=obj,
            type_label="seed",
            content_type_id=ct_id,
            title="",
            excerpt=body,
            author_display=obj.author.username if obj.author_id else "",
            sponsor_id=None,
            obj_status=obj.status,
            tags=[],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            working_item_references=wi_map.get(str(obj.pk), []),
        ))
    return pieces


def _normalise_leaves(qs, ct_id) -> list:
    ids = [o.pk for o in qs]
    wi_map = _build_wi_reference_map(ct_id, ids)
    pieces = []
    for obj in qs:
        body = obj.body_text or ""
        pieces.append(_make_piece(
            obj=obj,
            type_label="leaf",
            content_type_id=ct_id,
            title="",
            excerpt=body,
            author_display=obj.author.username if obj.author_id else "",
            sponsor_id=None,
            obj_status=obj.kind,
            tags=[],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            working_item_references=wi_map.get(str(obj.pk), []),
        ))
    return pieces


def _normalise_milldrafts(qs, ct_id) -> list:
    ids = [o.pk for o in qs]
    wi_map = _build_wi_reference_map(ct_id, ids)
    pieces = []
    for obj in qs:
        pieces.append(_make_piece(
            obj=obj,
            type_label="milldraft",
            content_type_id=ct_id,
            title=obj.title or "",
            excerpt=obj.grist_body or "",
            author_display=obj.author_name or (obj.author.username if obj.author_id else ""),
            sponsor_id=obj.sponsor_object_id,
            obj_status=obj.status,
            tags=[],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            working_item_references=wi_map.get(str(obj.pk), []),
        ))
    return pieces


def _normalise_feedbackitems(qs, ct_id) -> list:
    ids = [o.pk for o in qs]
    wi_map = _build_wi_reference_map(ct_id, ids)
    pieces = []
    for obj in qs:
        pieces.append(_make_piece(
            obj=obj,
            type_label="feedback",
            content_type_id=ct_id,
            title="",
            excerpt=obj.message or "",
            author_display=obj.user.username if obj.user_id else "",
            sponsor_id=None,
            obj_status=obj.status,
            tags=[],
            created_at=obj.created_at,
            updated_at=obj.created_at,  # FeedbackItem has no updated_at
            working_item_references=wi_map.get(str(obj.pk), []),
        ))
    return pieces


def _normalise_workingdocuments(qs, ct_id) -> list:
    ids = [o.pk for o in qs]
    wi_map = _build_wi_reference_map(ct_id, ids)
    pieces = []
    for obj in qs:
        excerpt = _prosemirror_to_text(obj.body_json)
        pieces.append(_make_piece(
            obj=obj,
            type_label="working_document",
            content_type_id=ct_id,
            title=obj.title or "",
            excerpt=excerpt,
            author_display=obj.user.username if obj.user_id else "",
            sponsor_id=None,
            obj_status="draft",
            tags=[],
            created_at=obj.created_at,
            updated_at=obj.last_saved_at or obj.updated_at,
            working_item_references=wi_map.get(str(obj.pk), []),
        ))
    return pieces


def _prosemirror_to_text(body_json: dict) -> str:
    if not body_json:
        return ""
    parts = []
    for node in body_json.get("content", []):
        for child in node.get("content", []):
            if child.get("type") == "text":
                parts.append(child.get("text", ""))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class UnifiedPieceListView(APIView):
    """
    GET /api/groups/<slug>/workbench/pieces/

    Returns a normalised Piece list across all raw Lane 1 content types in scope.
    Server-side union — one request, one response.

    Query params:
      type        — seed | leaf | milldraft | feedback | working_document
      q           — text search (title + excerpt, case-insensitive)
      status      — filter by source object status
      ungrouped   — true → only Pieces not yet in any WorkingItem
      ordering    — created_at | -created_at | updated_at | -updated_at (default: -updated_at)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not request.user.is_superuser:
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = get_object_or_404(Group, slug=slug)
        ct_group = ContentType.objects.get_for_model(group)

        type_filter = request.query_params.get("type")
        q = request.query_params.get("q", "").strip()
        status_filter = request.query_params.get("status")
        ungrouped = request.query_params.get("ungrouped") == "true"
        ordering = request.query_params.get("ordering", "-updated_at")

        pieces = []

        # -- Seeds (author-scoped; group members only) --
        if not type_filter or type_filter == "seed":
            from writing.models import Seed
            ct = ContentType.objects.get_for_model(Seed)
            qs = Seed.objects.filter(
                author__in=_group_member_users(group)
            ).select_related("author").exclude(status="failed")
            if status_filter:
                qs = qs.filter(status=status_filter)
            if q:
                qs = qs.filter(body_text__icontains=q) | qs.filter(transcript_text__icontains=q)
            pieces.extend(_normalise_seeds(qs, ct.pk))

        # -- Leaves --
        if not type_filter or type_filter == "leaf":
            from commons.models import Leaf
            ct = ContentType.objects.get_for_model(Leaf)
            qs = Leaf.objects.filter(
                author__in=_group_member_users(group)
            ).select_related("author")
            if status_filter:
                qs = qs.filter(kind=status_filter)
            if q:
                qs = qs.filter(body_text__icontains=q)
            pieces.extend(_normalise_leaves(qs, ct.pk))

        # -- MillDrafts (group-sponsored, unprocessed only) --
        if not type_filter or type_filter == "milldraft":
            from fundamentals.models import MillDraft, MillDraftStatus
            ct = ContentType.objects.get_for_model(MillDraft)
            qs = MillDraft.objects.filter(
                sponsor_content_type=ct_group,
                sponsor_object_id=group.pk,
            ).select_related("author").exclude(
                status__in=[MillDraftStatus.PROMOTED, MillDraftStatus.ARCHIVED]
            )
            if status_filter:
                qs = qs.filter(status=status_filter)
            if q:
                qs = qs.filter(title__icontains=q) | qs.filter(grist_body__icontains=q)
            pieces.extend(_normalise_milldrafts(qs, ct.pk))

        # -- FeedbackItems (not group-scoped — FeedbackBeacon has no group FK)
        # v0: superuser sees all non-shipped items. Scoping deferred to v1.
        if not type_filter or type_filter == "feedback":
            from feedback.models import FeedbackItem
            ct = ContentType.objects.get_for_model(FeedbackItem)
            qs = FeedbackItem.objects.select_related("user").exclude(status="shipped")
            if status_filter:
                qs = qs.filter(status=status_filter)
            if q:
                qs = qs.filter(message__icontains=q)
            pieces.extend(_normalise_feedbackitems(qs, ct.pk))

        # -- WorkingDocuments (draft WritingPieces sponsored by group) --
        if not type_filter or type_filter == "working_document":
            from writing.models import WorkingDocument
            ct = ContentType.objects.get_for_model(WorkingDocument)
            qs = WorkingDocument.objects.filter(
                piece__sponsor_content_type=ct_group,
                piece__sponsor_object_id=group.pk,
                piece__status="draft",
            ).select_related("user", "piece")
            if q:
                qs = qs.filter(title__icontains=q)
            pieces.extend(_normalise_workingdocuments(qs, ct.pk))

        # -- ungrouped filter --
        if ungrouped:
            grouped_keys = set(
                (ct_id, str(object_id))
                for ct_id, object_id in WorkingItemMembership.objects.values_list(
                    "piece_content_type_id", "piece_object_id"
                )
            )
            pieces = [
                p for p in pieces
                if (p["content_type_id"], p["id"]) not in grouped_keys
            ]

        # -- sort --
        reverse = ordering.startswith("-")
        sort_key = ordering.lstrip("-")
        if sort_key not in ("created_at", "updated_at"):
            sort_key = "updated_at"
            reverse = True

        pieces.sort(key=lambda p: p[sort_key] or datetime.min, reverse=reverse)

        return Response(pieces)


# ---------------------------------------------------------------------------
# Helper: group member user IDs
# ---------------------------------------------------------------------------

def _group_member_users(group):
    """Return a list of User PKs who are active members of the group."""
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType as CT
    from groups.models import GroupMembership

    User = get_user_model()
    user_ct = CT.objects.get_for_model(User)
    return (
        GroupMembership.objects
        .filter(group=group, member_content_type=user_ct, is_active=True)
        .values_list("member_object_id", flat=True)
    )
