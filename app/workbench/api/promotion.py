# workbench/api/promotion.py
#
# Phase 3 — Promotion endpoint.
# POST /api/groups/<slug>/workbench/working-items/<id>/promote
#
# Runs gate checks, creates WritingPiece + WorkingDocument, marks WorkingItem promoted.

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from workbench.models import WorkingItem, WorkingItemStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def _evaluate_gates(item: WorkingItem) -> tuple[bool, list[dict]]:
    """
    Evaluate promotion gates. Returns (all_hard_passed, failures).
    failures: [{gate, message, hard}]
    """
    failures = []

    # Hard: title required
    if not (item.title or "").strip():
        failures.append({
            "gate": "title_required",
            "message": "A title is required before promotion.",
            "hard": True,
        })

    # Hard: status must be ready
    if item.status != WorkingItemStatus.READY:
        failures.append({
            "gate": "status_ready",
            "message": f"WorkingItem must be in 'ready' status (currently '{item.status}').",
            "hard": True,
        })

    # Soft: spellcheck (default: warning only)
    if not item.spellcheck_passed:
        failures.append({
            "gate": "spellcheck",
            "message": "Spellcheck has not been passed. You can override this.",
            "hard": False,
        })

    all_hard_passed = all(not f["hard"] for f in failures)
    return all_hard_passed, failures


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class WorkingItemPromoteView(APIView):
    """
    POST /api/groups/<slug>/workbench/working-items/<id>/promote

    Body (optional):
      override_soft_gates: true   — proceed despite soft gate failures

    On success (201):
      { writing_piece_id, working_document_id, working_item_id, gate_warnings }

    On hard gate failure (400):
      { detail, failures: [{gate, message, hard}] }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, item_id):
        if not request.user.is_superuser:
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = get_object_or_404(Group, slug=slug)
        ct_group = ContentType.objects.get_for_model(group)
        item = get_object_or_404(
            WorkingItem,
            id=item_id,
            sponsor_content_type=ct_group,
            sponsor_object_id=group.pk,
        )

        if item.status == WorkingItemStatus.PROMOTED:
            return Response(
                {"detail": "This WorkingItem has already been promoted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if item.status == WorkingItemStatus.ARCHIVED:
            return Response(
                {"detail": "Archived WorkingItems cannot be promoted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Gate evaluation ---
        all_hard_passed, failures = _evaluate_gates(item)
        override = request.data.get("override_soft_gates", False) is True

        hard_failures = [f for f in failures if f["hard"]]
        soft_failures = [f for f in failures if not f["hard"]]

        if hard_failures:
            return Response(
                {
                    "detail": "Promotion blocked by required gate failures.",
                    "failures": failures,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if soft_failures and not override:
            return Response(
                {
                    "detail": "Promotion has soft gate warnings. Pass override_soft_gates=true to proceed.",
                    "failures": soft_failures,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Promote ---
        with transaction.atomic():
            from writing.models import WritingPiece, WorkingDocument

            # Create WritingPiece
            writing_piece = WritingPiece(
                sponsor_content_type=ct_group,
                sponsor_object_id=group.pk,
                author=item.author,
                submitted_by=request.user,
                title=item.title,
                body_json=item.body_json,
                writing_kind=item.target_writing_kind or "post",
                status="draft",
            )
            writing_piece.save()

            # Create WorkingDocument for the new piece
            working_doc = WorkingDocument.objects.create(
                piece=writing_piece,
                user=request.user,
                body_json=item.body_json,
                title=item.title,
            )

            # Mark WorkingItem as promoted
            item.promoted_to = writing_piece
            item.promoted_at = timezone.now()
            item.status = WorkingItemStatus.PROMOTED
            item.save(update_fields=["promoted_to", "promoted_at", "status", "updated_at"])

        logger.info(
            "workbench_promoted item=%s writing_piece=%s group=%s user=%s",
            item.pk, writing_piece.pk, slug, request.user.username,
        )

        return Response(
            {
                "writing_piece_id": str(writing_piece.pk),
                "working_document_id": str(working_doc.pk),
                "working_item_id": str(item.pk),
                "gate_warnings": soft_failures,
            },
            status=status.HTTP_201_CREATED,
        )
