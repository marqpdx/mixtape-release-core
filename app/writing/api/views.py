# writing/api/views.py

import logging

from django.contrib.contenttypes.models import ContentType
import uuid
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.utils.text import get_valid_filename
from django.db import transaction
from django.db.models import F, Max, Q
from django.db.models.functions import Length, Trim
from django.shortcuts import get_object_or_404
from django.utils import dateparse, timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from groups.services.permissions import PermissionService
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.api.permissions import IsAuthorOrStaff
from files.models import StoredFile
from writing.models import (
    Seed,
    SplitSuggestion,
    WritingComment,
    WritingAnalysisSession,
    WritingSuggestedRevision,
    WritingPiece,
    # WritingPlacement,  # Deprecated - replaced by ContentPlacement
    WritingSeries,
    WorkingDocument,
    WritingSynopsis,
)
from writing.services import promote_seed_to_working_copy
from writing.tasks import transcribe_seed_task
from writing.analysis_export import (
    build_analysis_export,
    compute_source_revision_hash,
    get_export_source_for_user,
)
from writing.suggested_revision import create_suggested_revision_from_session
from writing.pdf_export import (
    build_pdf_export_response,
    get_pdf_export_source_for_user,
)

logger = logging.getLogger(__name__)

MAX_SEED_AUDIO_BYTES = 20 * 1024 * 1024  # 20MB
ALLOWED_AUDIO_PREFIXES = ("audio/",)
ALLOWED_AUDIO_MIME = ("video/webm",)

MAX_INLINE_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_INLINE_IMAGE_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}

from ..models import WritingPiece, is_provisional_slug
from ..permissions import (
    CanEditWritingPiece,
    CanEditWritingPieceDetails,
    CanPublishWritingPiece,
    can_edit_others_group_writing,
)
from .serializers import (
    SeedSerializer,
    SeedUpdateSerializer,
    SplitSuggestionSerializer,
    WritingAnalysisExportRequestSerializer,
    WritingAnalysisSessionSerializer,
    WritingFidelityReportSerializer,
    WritingSuggestedRevisionCreateSerializer,
    WritingSuggestedRevisionSerializer,
    WritingCommentSerializer,
    WritingPieceDetailSerializer,
    WritingPieceSerializer,
    # WritingPlacementSerializer,  # Deprecated - replaced by ContentPlacement
    WorkingDocumentLightSerializer,
)


class WorkingDocumentUpsertView(generics.GenericAPIView):
    """
    PUT: Upsert the working document for the current user.
    GET: (optional) Return current working document if exists.
    """
    serializer_class = WorkingDocumentLightSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def get(self, request, pk=None):
        piece = self.get_piece(pk)
        from writing.services import WorkingCopyConflict, get_editing_document
        try:
            wc = get_editing_document(piece, request.user, create=True)
        except WorkingCopyConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        data = self.get_serializer(wc).data

        # bootstrapped_at is None: this WC has never been checked against piece.body_json.
        # For solo docs where piece.body_json is richer (e.g. imported pieces where WC
        # was never edited), bootstrap once and set the flag so this never repeats.
        # bootstrapped_at is set: skip — either already bootstrapped, or user-edited.
        if wc.bootstrapped_at is None and piece.sponsor_content_type and piece.sponsor_content_type.model == "group":
            if not (wc.body_json or {}).get("content") and (piece.body_json or {}).get("content"):
                data["body_json"] = piece.body_json
                WorkingDocument.objects.filter(pk=wc.pk).update(
                    body_json=piece.body_json,
                    bootstrapped_at=timezone.now(),
                )
            else:
                WorkingDocument.objects.filter(pk=wc.pk).update(bootstrapped_at=timezone.now())
        elif wc.bootstrapped_at is None:
            piece_has_content = (
                piece.body_json
                and isinstance(piece.body_json, dict)
                and piece.body_json.get("content")
            )
            if piece_has_content:
                wc_body = data.get("body_json")
                wc_nodes = len(wc_body.get("content", [])) if isinstance(wc_body, dict) else 0
                piece_nodes = len(piece.body_json["content"])
                if wc_nodes < piece_nodes:
                    data["body_json"] = piece.body_json
                    WorkingDocument.objects.filter(pk=wc.pk).update(
                        body_json=piece.body_json,
                        bootstrapped_at=timezone.now(),
                    )
            else:
                WorkingDocument.objects.filter(pk=wc.pk).update(
                    bootstrapped_at=timezone.now(),
                )

        return Response(data)

    @transaction.atomic
    def put(self, request, pk=None):
        piece = self.get_piece(pk)
        piece = WritingPiece.objects.select_for_update().get(pk=piece.pk)
        from writing.services import WorkingCopyConflict, get_editing_document
        try:
            wc = get_editing_document(piece, request.user, create=True, lock=True)
        except WorkingCopyConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        shared_group_draft = (
            piece.sponsor_content_type and piece.sponsor_content_type.model == "group"
            and wc.dispatch_content_id is None
        )
        expected = request.data.get("expected_auto_save_count")
        if shared_group_draft and expected is None:
            return Response({"detail": "Draft revision is required. Reload before editing."}, status=status.HTTP_409_CONFLICT)
        if expected is not None and str(wc.auto_save_count) != str(expected):
            return Response({"detail": "This draft changed elsewhere. Reload before saving."}, status=status.HTTP_409_CONFLICT)

        payload = request.data.copy()
        payload.pop("expected_auto_save_count", None)
        ser = self.get_serializer(instance=wc, data=payload, partial=True)
        ser.is_valid(raise_exception=True)
        body_changed = "body_json" in ser.validated_data and ser.validated_data["body_json"] != wc.body_json
        wc = ser.save()
        WorkingDocument.objects.filter(pk=wc.pk).update(
            auto_save_count=F("auto_save_count") + 1,
            bootstrapped_at=timezone.now(),
        )
        wc.refresh_from_db()
        if body_changed:
            piece.spellcheck_clean = False
            piece.signed_off = False
            piece.signed_off_by = None
            piece.save(update_fields=["spellcheck_clean", "signed_off", "signed_off_by", "updated_at"])

        # Suggested excerpt: only fills in while the field is blank, so it
        # never overwrites anything the user has typed. Recomputed on every
        # autosave until the user provides their own excerpt (or clears it,
        # which re-enables the suggestion).
        if not wc.excerpt.strip():
            from utils.writing.writing_utils import generate_excerpt_from_prosemirror
            suggested = generate_excerpt_from_prosemirror(wc.body_json or {}, max_length=200)
            if suggested:
                wc.excerpt = suggested
                wc.save(update_fields=["excerpt"])

        response_data = self.get_serializer(wc).data
        response_data["split_suggestion_status"] = _check_and_trigger_split_suggestion(piece, wc)
        return Response(response_data, status=status.HTTP_200_OK)


def _check_and_trigger_split_suggestion(piece, wc) -> str | None:
    """
    Check split suggestion conditions on autosave. Returns the current suggestion status
    (or None). Supersedes stale suggestions and queues a new task when conditions are met.
    """
    from utils.writing.writing_utils import count_words_in_prosemirror
    from writing.tasks import generate_split_suggestion_task

    # Return current active suggestion status regardless of conditions
    active = (
        SplitSuggestion.objects
        .filter(piece=piece)
        .exclude(status__in=["executed", "superseded", "declined"])
        .order_by("-created_at")
        .first()
    )

    if not piece.suggest_splits or not piece.target_wordcount:
        return active.status if active else None

    word_count = count_words_in_prosemirror(wc.body_json or {})
    if word_count < piece.target_wordcount * 1.15:
        return active.status if active else None

    # Already have a pending or accepted suggestion — don't queue another
    if active and active.status in ("pending", "accepted"):
        return active.status

    # Supersede any ready/shown suggestion (stale split points)
    SplitSuggestion.objects.filter(
        piece=piece,
        status__in=("ready", "shown"),
    ).update(status="superseded", updated_at=timezone.now())

    suggestion = SplitSuggestion.objects.create(
        piece=piece,
        word_count_at_suggestion=word_count,
    )
    generate_split_suggestion_task.apply_async(
        kwargs={"suggestion_id": str(suggestion.id)},
    )
    logger.info("[split] Queued suggestion %s for piece %s (wc=%d)", suggestion.id, piece.id, word_count)
    return "pending"


class WritingPieceSplitSuggestionView(generics.GenericAPIView):
    """
    GET  /api/writing/pieces/<pk>/split-suggestion  — current non-terminal suggestion
    POST /api/writing/pieces/<pk>/split-suggestion  — act on it

    POST body: {"action": "view" | "dismiss" | "decline"}
      view    → transitions to 'shown' (writer sees rationale; markers come in Phase 3)
      dismiss → 'dismissed'; suggest_splits stays True; will fire again at next threshold
      decline → 'declined' + sets piece.suggest_splits=False ("sets it in stone")
    """
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def _get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def _get_active_suggestion(self, piece):
        return (
            SplitSuggestion.objects
            .filter(piece=piece)
            .exclude(status__in=["executed", "superseded", "declined"])
            .order_by("-created_at")
            .first()
        )

    def get(self, request, pk):
        piece = self._get_piece(pk)
        suggestion = self._get_active_suggestion(piece)
        if not suggestion:
            return Response({"status": None, "suggestions": []})
        return Response(SplitSuggestionSerializer(suggestion).data)

    def post(self, request, pk):
        piece = self._get_piece(pk)
        action = request.data.get("action")

        if action not in ("view", "dismiss", "decline"):
            return Response(
                {"detail": "action must be one of: view, dismiss, decline"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suggestion = self._get_active_suggestion(piece)
        if not suggestion or suggestion.status not in ("ready", "shown"):
            return Response(
                {"detail": "No actionable suggestion found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "view":
            suggestion.status = "shown"
            suggestion.save(update_fields=["status", "updated_at"])

        elif action == "dismiss":
            suggestion.status = "dismissed"
            suggestion.save(update_fields=["status", "updated_at"])

        elif action == "decline":
            suggestion.status = "declined"
            suggestion.save(update_fields=["status", "updated_at"])
            WritingPiece.objects.filter(pk=piece.pk).update(suggest_splits=False)

        return Response(SplitSuggestionSerializer(suggestion).data)


class WorkingDocumentApplyView(generics.GenericAPIView):
    """
    POST: Merge the user's working document into the canonical piece and snapshot if published.
    """
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    @transaction.atomic
    def post(self, request, pk=None):
        piece = get_object_or_404(WritingPiece.objects.select_for_update(), pk=pk)
        self.check_object_permissions(request, piece)

        from writing.services import WorkingCopyConflict, get_editing_document
        try:
            wc = get_editing_document(piece, request.user, lock=True)
        except WorkingCopyConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        if wc is None:
            return Response({"detail": "No working copy exists."}, status=status.HTTP_404_NOT_FOUND)
        changed = wc.apply_to_piece(piece)
        if changed and piece.is_published:
            piece.create_version(content_changed=True)
        return Response(self.get_serializer(piece).data, status=status.HTTP_200_OK)


class WritingPiecePdfExportView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def _get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def get(self, request, pk):
        piece = self._get_piece(pk)
        source = get_pdf_export_source_for_user(piece, request.user)
        return build_pdf_export_response(
            piece=piece,
            title=source["title"],
            excerpt=source["excerpt"],
            body_json=source["body_json"],
            source_kind=source["source_kind"],
        )


class WritingPieceAnalysisExportView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]
    serializer_class = WritingAnalysisExportRequestSerializer

    def _get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def post(self, request, pk):
        piece = self._get_piece(pk)
        serializer = self.get_serializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)

        export_source = get_export_source_for_user(piece, request.user)
        source_revision_hash = compute_source_revision_hash(
            title=export_source["title"],
            excerpt=export_source["excerpt"],
            body_json=export_source["body_json"],
        )
        export_payload = build_analysis_export(
            piece=piece,
            title=export_source["title"],
            excerpt=export_source["excerpt"],
            body_json=export_source["body_json"],
            source_revision_hash=source_revision_hash,
            source_kind=export_source["source_kind"],
            working_document_id=export_source["working_document_id"],
        )
        export_payload["source"]["exported_at"] = timezone.now().isoformat()

        session = WritingAnalysisSession.objects.create(
            source_piece=piece,
            created_by=request.user,
            source_revision_hash=source_revision_hash,
            export_version=WritingAnalysisSession.EXPORT_VERSION_V1,
            planner_type=serializer.validated_data.get("planner_type", ""),
            planner_label=serializer.validated_data.get("planner_label", ""),
            status=WritingAnalysisSession.Status.EXPORTED,
            export_payload=export_payload,
        )

        return Response(
            {
                "session": WritingAnalysisSessionSerializer(session).data,
                "export": export_payload,
            },
            status=status.HTTP_201_CREATED,
        )


class WritingPieceSuggestedRevisionCreateView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]
    serializer_class = WritingSuggestedRevisionCreateSerializer

    def _get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def post(self, request, pk, session_id):
        piece = self._get_piece(pk)
        serializer = self.get_serializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)

        session = get_object_or_404(
            WritingAnalysisSession,
            pk=session_id,
            source_piece=piece,
        )
        export_source = ((session.export_payload or {}).get("source") or {})
        if session.source_revision_hash != export_source.get("body_json_revision_hash"):
            return Response(
                {"detail": "Analysis session source revision is inconsistent."},
                status=status.HTTP_409_CONFLICT,
            )
        if session.status == WritingAnalysisSession.Status.STALE:
            return Response({"detail": "Analysis session is stale."}, status=status.HTTP_409_CONFLICT)

        existing_revision = (
            WritingSuggestedRevision.objects
            .filter(analysis_session=session)
            .select_related("suggested_piece")
            .order_by("-created_at")
            .first()
        )
        if existing_revision:
            return Response(
                {
                    "detail": "A suggested revision already exists for this session.",
                    "suggested_revision": WritingSuggestedRevisionSerializer(existing_revision).data,
                    "fidelity_report": WritingFidelityReportSerializer(existing_revision.fidelity_report).data if hasattr(existing_revision, "fidelity_report") else None,
                    "piece": WritingPieceSerializer(existing_revision.suggested_piece, context={"request": request}).data,
                },
                status=status.HTTP_200_OK,
            )

        suggested_piece, suggested_revision, fidelity_report = create_suggested_revision_from_session(
            session=session,
            acting_user=request.user,
            title_suffix=serializer.validated_data.get("title_suffix", "Suggested Revision"),
        )
        return Response(
            {
                "suggested_revision": WritingSuggestedRevisionSerializer(suggested_revision).data,
                "fidelity_report": WritingFidelityReportSerializer(fidelity_report).data,
                "piece": WritingPieceSerializer(suggested_piece, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WritingPieceListCreateView(generics.ListCreateAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = WritingPiece.objects.filter(author=self.request.user)

        from dispatch.access import active_group_ids
        from groups.models import Group
        group_type = ContentType.objects.get_for_model(Group)
        revoked_dispatch_drafts = WritingPiece.objects.filter(
            status="draft",
            sponsor_content_type=group_type,
            working_copies__dispatch_content__isnull=False,
        ).exclude(sponsor_object_id__in=active_group_ids(self.request.user)).values("pk")
        qs = qs.exclude(pk__in=revoked_dispatch_drafts)

        status_param = self.request.query_params.get("status")
        if status_param in {"draft", "published", "scheduled", "archived"}:
            qs = qs.filter(status=status_param)

        # Always filter out empty pieces from user-facing lists
        qs = qs.filter(is_empty=False)

        kind = self.request.query_params.get("writing_kind")
        if kind:
            qs = qs.filter(writing_kind=kind)

        pinned_only = self.request.query_params.get("pinned_only")
        if pinned_only in ("1", "true", "True"):
            qs = qs.filter(pinned_at__isnull=False)

        return qs.select_related(
            "author",
            "author__profile",
            "sponsor_content_type"
        ).prefetch_related(
            "versions"
        ).order_by("-pinned_at", "-published_at", "-updated_at")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def create(self, request, *args, **kwargs):
        """Override to optionally create WorkingCopy alongside WritingPiece"""
        with transaction.atomic():
            # Create the WritingPiece (is_empty will be handled by serializer)
            response = super().create(request, *args, **kwargs)

            # Check if we should create a working copy
            create_working_copy = request.data.get("create_working_copy", False)

            if create_working_copy and response.status_code == 201:
                piece_id = response.data["id"]
                piece = WritingPiece.objects.get(pk=piece_id)

                # Create working copy
                working_copy = WorkingDocument.objects.create(
                    piece=piece,
                    user=request.user,
                    title=piece.title,
                    body_json=piece.body_json,
                    excerpt=piece.excerpt,
                )
                # Add working copy to response
                working_copy_data = WorkingDocumentLightSerializer(working_copy).data
                response.data["working_copy"] = working_copy_data

        return response


class WritingPieceRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPieceDetails]
    lookup_field = "pk"

    def get_queryset(self):
        return WritingPiece.objects.all()


class WritingPiecePublicView(generics.RetrieveAPIView):
    """
    Retrieve a single published WritingPiece by slug (sponsor-agnostic).
    Used for public viewing of published content.

    GET /api/writing/pieces/view/{slug}
    """
    permission_classes = [permissions.AllowAny]  # Visibility checks done in get_queryset
    lookup_field = "slug"

    def get_serializer_class(self):
        from writing.api.serializers import WritingPieceDetailSerializer
        return WritingPieceDetailSerializer

    def get_queryset(self):
        # Base queryset: published pieces only
        queryset = WritingPiece.objects.filter(
            status="published"
        ).select_related(
            "author",
            "author__profile",
            "sponsor_content_type",
            "series",
        ).prefetch_related(
            "versions"
        )

        # TODO: Add visibility filtering based on placements if needed
        # For now, all published pieces are viewable
        # You can add logic here to check placement visibility

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Override to resolve artifact payload from placements"""
        instance = self.get_object()
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        placements = ContentPlacement.objects.filter(
            source_content_type=ct_piece,
            source_object_id=instance.id,
            channel__in=["feed", "shelf"],
        ).order_by("-created_at")

        user = request.user if request.user.is_authenticated else None
        selected = None
        for placement in placements:
            if can_view_placement(placement, user):
                selected = placement
                break

        if not selected:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = get_display_payload(selected)
        metadata = payload.get("metadata") or {}

        instance.increment_view_count()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if metadata.get("title"):
            data["title"] = metadata["title"]
        if metadata.get("excerpt") is not None:
            data["excerpt"] = metadata["excerpt"]
        if metadata.get("body_json") is not None:
            data["body_json"] = metadata["body_json"]
        data["placement_id"] = str(selected.id)
        data["placement_visibility"] = selected.visibility
        data["placement_channel"] = selected.channel
        return Response(data)


class WritingPieceDetailView(generics.RetrieveAPIView):
    """
    DEPRECATED: Use WritingPiecePublicView instead.
    Retrieve a single WritingPiece by slug within a group context.
    Enforces visibility and permission checks.

    GET /api/groups/{group_slug}/writing/{piece_slug}
    """
    serializer_class = WritingPieceDetailSerializer
    permission_classes = [permissions.AllowAny]  # Visibility checks done in get_queryset
    lookup_field = "slug"
    lookup_url_kwarg = "piece_slug"

    def get_queryset(self):
        group_slug = self.kwargs.get("group_slug")
        get_object_or_404(Group, slug=group_slug)

        # Base queryset: published pieces. Placement visibility is enforced in retrieve().
        queryset = WritingPiece.objects.filter(
            status="published",
        ).select_related(
            "author",
            "author__profile",
            "sponsor_content_type",
        ).prefetch_related(
            "versions",
        ).distinct()

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Override to resolve artifact payload from placements"""
        instance = self.get_object()
        group_slug = self.kwargs.get("group_slug")
        group = get_object_or_404(Group, slug=group_slug)
        placements = ContentPlacement.objects.filter(
            source_object_id=instance.id,
            target_object_id=group.id,
            channel="feed",
        ).order_by("-created_at")

        user = request.user if request.user.is_authenticated else None
        selected = None
        for placement in placements:
            if can_view_placement(placement, user):
                selected = placement
                break

        if not selected:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = get_display_payload(selected)
        metadata = payload.get("metadata") or {}

        instance.increment_view_count()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if metadata.get("title"):
            data["title"] = metadata["title"]
        if metadata.get("excerpt") is not None:
            data["excerpt"] = metadata["excerpt"]
        if metadata.get("body_json") is not None:
            data["body_json"] = metadata["body_json"]
        data["placement_id"] = str(selected.id)
        data["placement_visibility"] = selected.visibility
        data["placement_channel"] = selected.channel
        return Response(data)


class WritingPieceScheduleView(generics.GenericAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanPublishWritingPiece]

    def post(self, request, pk=None):
        from django.utils.dateparse import parse_datetime
        piece = get_object_or_404(WritingPiece, pk=pk, author=request.user)
        self.check_object_permissions(request, piece)

        dt = parse_datetime(request.data.get("scheduled_for") or "")
        if not dt:
            return Response({"detail": "scheduled_for (ISO8601) is required."}, status=status.HTTP_400_BAD_REQUEST)

        wc = WorkingDocument.objects.filter(piece=piece, user=request.user).first()
        if wc:
            wc.apply_to_piece(piece)

        piece.publish(scheduled_for=dt)
        return Response(self.get_serializer(piece).data, status=status.HTTP_200_OK)


class WritingPiecePinView(generics.GenericAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanPublishWritingPiece]

    def post(self, request, pk=None):
        piece = get_object_or_404(WritingPiece, pk=pk, author=request.user)
        self.check_object_permissions(request, piece)
        rank = request.data.get("rank")
        piece.pin(rank=rank if isinstance(rank, int) else None)
        return Response(self.get_serializer(piece).data, status=status.HTTP_200_OK)


class WritingPieceUnpinView(generics.GenericAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanPublishWritingPiece]

    def post(self, request, pk=None):
        piece = get_object_or_404(WritingPiece, pk=pk, author=request.user)
        self.check_object_permissions(request, piece)
        piece.unpin()
        return Response(self.get_serializer(piece).data, status=status.HTTP_200_OK)



class SeedListCreateView(generics.ListCreateAPIView):
    """
    GET  /seeds/        -> list current user's seeds (author-scoped)
    POST /seeds/        -> create a seed (optionally with body_text)
    """
    serializer_class = SeedSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    # Optional: throttle list/create if you want (see notes below)
    throttle_scope = "seeds_list_create"
    pagination_class = None  # Disable pagination for now; could add later if needed

    def get_queryset(self):
        user = self.request.user
        qs = Seed.objects.all() if (user.is_staff and self.request.query_params.get("all") == "1") else Seed.objects.filter(author=user)

        include_empty = self.request.query_params.get("include_empty") == "1"
        if not include_empty:
            qs = qs.annotate(tlen=Length(Trim("body_text"))).filter(
                Q(tlen__gt=0) | Q(kind="voice")
            )

        return qs.order_by("-updated_at")

    def create(self, request, *args, **kwargs):
        audio_file = request.FILES.get("audio_file")
        if audio_file:
            if audio_file.size > MAX_SEED_AUDIO_BYTES:
                return Response(
                    {"detail": f"Audio file too large (max {MAX_SEED_AUDIO_BYTES // (1024 * 1024)}MB)."},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )

            content_type = (audio_file.content_type or "").lower()
            if not (content_type.startswith(ALLOWED_AUDIO_PREFIXES) or content_type in ALLOWED_AUDIO_MIME):
                return Response(
                    {"detail": f"Unsupported audio type: {content_type or 'unknown'}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            base = get_valid_filename(audio_file.name or "")
            ext = (base.rsplit(".", 1)[-1].lower() if "." in base else "")
            unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())
            s3_key = f"seeds/audio/{request.user.id}/{unique}"

            audio_file.seek(0)
            saved_key = default_storage.save(s3_key, audio_file)

            stored = StoredFile.objects.create(
                file_path=saved_key,
                file_name=audio_file.name or "",
                file_type=audio_file.content_type or "",
                file_size=audio_file.size or 0,
                uploaded_by=request.user,
                source=request.data.get("source") or "web",
            )

            seed = Seed.objects.create(
                author=request.user,
                body_text="Transcribing voice note…",
                kind="voice",
                status="processing",
                audio_file=stored,
                context_url=request.data.get("context_url") or request.data.get("url"),
                source=request.data.get("source") or "web",
            )

            transcribe_seed_task.delay(str(seed.id))

            data = SeedSerializer(seed).data
            headers = self.get_success_headers(data)
            return Response(data, status=status.HTTP_201_CREATED, headers=headers)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class SeedDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /seeds/<id>/
    PATCH  /seeds/<id>/   -> autosave body_text (uses SeedUpdateSerializer)
    DELETE /seeds/<id>/
    """
    queryset = Seed.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrStaff]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_scope = "seeds_detail"

    def get_serializer_class(self):
        # Use the tighter serializer for updates (autosave)
        if self.request.method in ("PUT", "PATCH"):
            return SeedUpdateSerializer
        return SeedSerializer

    def perform_destroy(self, instance):
        super().perform_destroy(instance)


class SeedPromoteView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrStaff]
    throttle_scope = "seeds_promote"

    def post(self, request, pk):
        seed = generics.get_object_or_404(Seed, pk=pk)
        self.check_object_permissions(request, seed)
        wc = promote_seed_to_working_copy(seed=seed, requested_by=request.user, extra_meta=request.data or None)
        return Response({"id": str(wc.id), "title": getattr(wc, "title", "Untitled")}, status=status.HTTP_201_CREATED)


class SeedIngestView(generics.CreateAPIView):
    """
    Accepts:
      - JSON: { text, url?, source? }
      - form-data: 'text', 'url', 'source'
    Creates a Seed for the current user.
    """
    serializer_class = SeedSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_scope = "seeds_ingest"

    # We don't want clients to set context fields via serializer directly,
    # so override perform_create to pull fields from request.
    def create(self, request, *args, **kwargs):
        content_type = (request.content_type or "").lower()
        if "application/json" in content_type:
            text = (request.data.get("text") or "").strip()
            context_url = request.data.get("url") or request.data.get("context_url")
            source = request.data.get("source") or "web"
        else:
            text = (request.data.get("text") or "").strip()
            context_url = request.data.get("url") or request.data.get("context_url")
            source = request.data.get("source") or "web"

        if not text:
            return Response({"detail": "Missing 'text'."}, status=status.HTTP_400_BAD_REQUEST)

        seed = Seed.objects.create(
            author=request.user,
            body_text=text,
            context_url=context_url,
            source=source,
        )
        data = SeedSerializer(seed).data
        headers = self.get_success_headers(data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

def apply_teaser_override(opts: dict, fallback_excerpt: str | None):
    # If is_excerpt=True, ensure overrides.excerpt_override is present
    if opts.get("is_excerpt"):
        ov = (opts.get("overrides") or {}).copy()
        if not ov.get("excerpt_override") and fallback_excerpt:
            ov["excerpt_override"] = fallback_excerpt
        opts["overrides"] = ov
    return opts


class WritingPiecePublishAndPlaceView(generics.GenericAPIView):
    """
    Publish (or schedule) and create placements in one go.

    Expected payload (fields optional unless noted):
    {
      "title": "Optional final title",
      "body_json": {...},
      "excerpt": "Optional excerpt",
      "writing_kind": "post|article|announcement|...",
      "scheduled_for": "2025-09-21T10:00:00Z",  // if present -> scheduled
      "canonical_url": "https://...",
      "tags": ["tag1","tag2"],

      "destinations": {
        "personal": true,
        "groups": ["group-slug-1","group-uuid-2"],
        "shelves": ["library-uuid-1"],
        "lantern": false
      },

      // Defaults applied to all placements unless overridden per-target:
      "placement_options": {
        "visibility": "public",               // "public"|"members"|"private"|"scheduled"
        "follow_updates": false,              // if false, locks to an artifact
        "is_excerpt": false,
        "fragment_selector": {...},           // optional JSON
        "overrides": { "title_override": "...", "excerpt_override": "...", "lantern_subject": "..." },
        "order": 0,
        "is_pinned": false
      },

      // Per-group overrides keyed by slug or id (same keys used in destinations.groups)
      "group_overrides": {
        "group-slug-1": {
          "visibility": "members",
          "is_pinned": true,
          "order": 1
        }
      },

      "audience": "just_me" | "readers",
      "addressed_to": "public" | "crossroads" | "self"
    }
    """
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanPublishWritingPiece]

    def get_piece(self, pk):
        piece = get_object_or_404(
            WritingPiece.objects.select_related("sponsor_content_type", "author"),
            pk=pk
        )
        self.check_object_permissions(self.request, piece)
        return piece

    def post(self, request, pk=None):
        from publishing.serializers import ContentPlacementSerializer
        from writing.publish_service import publish_and_place
        from atelier.services import get_readiness_warnings

        piece = self.get_piece(pk)

        if piece.is_empty:
            return Response({"error": "Cannot publish empty content"}, status=400)

        readiness_warnings = get_readiness_warnings(piece)

        try:
            result = publish_and_place(piece, request.user, request.data or {})
        except ValidationError as ve:
            return Response({"error": ve.message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("Publish & place failed", extra={"piece_id": str(pk), "user_id": str(request.user.id)})
            return Response({"error": "Publish & place failed. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        piece = result["piece"]
        msg_base = "scheduled" if result["scheduled"] else "published"
        serializer = self.get_serializer(piece, context={"request": request})
        return Response({
            "id": str(piece.id),
            "piece": serializer.data,
            "placements_created": result["placements_created"],
            "placements": ContentPlacementSerializer(result["placements"], many=True, context={"request": request}).data,
            "publication_group_id": str(result["pub_group"].id) if result["pub_group"] else None,
            "message": f'Successfully {msg_base} "{piece.title}" to {result["placements_created"]} destination(s).',
            "readiness_warnings": readiness_warnings,
        }, status=status.HTTP_200_OK)


class WritingPieceUnpublishView(generics.GenericAPIView):
    """
    Unpublish a piece and return it to draft status.

    POST /api/writing/pieces/<uuid:pk>/unpublish
    """
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanPublishWritingPiece]

    def post(self, request, pk=None):
        piece = get_object_or_404(
            WritingPiece.objects.select_related("sponsor_content_type", "author"),
            pk=pk
        )
        self.check_object_permissions(request, piece)

        piece.unpublish()

        return Response(
            {
                "message": "Piece unpublished and returned to draft.",
                "piece": self.get_serializer(piece).data,
            },
            status=status.HTTP_200_OK,
        )


class WritingCommentListCreateView(generics.ListCreateAPIView):
    serializer_class = WritingCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        piece_id = self.kwargs["piece_id"]
        group_slug = self.kwargs["group_slug"]

        # Verify user can access this group's content
        group = get_object_or_404(Group, slug=group_slug)
        if not group.can_user_view_content(self.request.user):
            return WritingComment.objects.none()

        # Only return top-level comments (replies are nested in serializer)
        return WritingComment.objects.filter(
            piece_id=piece_id,
            parent__isnull=True,
            is_approved=True
        ).select_related(
            "author",
            "author__profile"
        ).prefetch_related(
            "replies__author",
            "replies__author__profile",
            "likes",
            "replies__likes"
        )

    def perform_create(self, serializer):
        piece_id = self.kwargs["piece_id"]
        piece = get_object_or_404(WritingPiece, id=piece_id)
        serializer.save(author=self.request.user, piece=piece)









import logging

from rest_framework.decorators import api_view


logger = logging.getLogger(__name__)

# New endpoint to clear empty flag
@api_view(["PATCH"])
def clear_empty_flag(request, piece_id):
    if not request.user.is_authenticated:
        from rest_framework.exceptions import NotAuthenticated
        raise NotAuthenticated()
    logger.info(f"clear_empty_flag called for piece_id: {piece_id}")
    piece = get_object_or_404(WritingPiece, id=piece_id, author=request.user)
    logger.info(f"Found piece {piece.id}, is_empty={piece.is_empty}")

    # Use update() to bypass the save() method which auto-recalculates is_empty
    WritingPiece.objects.filter(id=piece_id).update(is_empty=False)

    # Verify it was saved
    piece.refresh_from_db()
    logger.info(f"After update, is_empty={piece.is_empty}")

    return Response({"status": "success", "is_empty": piece.is_empty})


# === Collaboration Management ===

class WorkingDocumentEnableCollaborationView(generics.GenericAPIView):
    """
    POST: Enable collaboration on a working document.
    Creates DispatchContent and optionally adds initial collaborators.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_id=None):
        from dispatch.models import DispatchContent, DispatchCollaborator
        from dispatch.api.serializers import DispatchContentSerializer
        from writing.models import WorkingDocument

        # Get working document
        working_doc = get_object_or_404(
            WorkingDocument.objects.select_related('dispatch_content'),
            piece_id=piece_id,
            user=request.user,   # important: unique_together(piece, user)
        )

        # Check if already collaborative
        if working_doc.dispatch_content:
            return Response(
                {"error": "Collaboration already enabled"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create DispatchContent
        with transaction.atomic():
            dispatch_content = DispatchContent.objects.create(
                created_by=request.user,
                content_snapshot=working_doc.body_json or {}
            )

            # Link to working document
            working_doc.dispatch_content = dispatch_content
            working_doc.save()

            # Add creator as editor
            DispatchCollaborator.objects.create(
                content=dispatch_content,
                user=request.user,
                role='editor',
                invited_by=request.user
            )

            # Add additional collaborators if provided
            collaborator_data = request.data.get('collaborators', [])
            for collab in collaborator_data:
                user_id = collab.get('user_id')
                role = collab.get('role', 'editor')

                if user_id and user_id != request.user.id:
                    DispatchCollaborator.objects.get_or_create(
                        content=dispatch_content,
                        user_id=user_id,
                        defaults={
                            'role': role,
                            'invited_by': request.user
                        }
                    )

        # Return the dispatch content
        serializer = DispatchContentSerializer(dispatch_content)
        return Response({
            "dispatch_content": serializer.data,
            "message": "Collaboration enabled successfully"
        }, status=status.HTTP_201_CREATED)


class WorkingDocumentRescindCollaborationView(generics.GenericAPIView):
    """
    POST: Rescind collaboration on a working document.
    Only allowed if no collaborative edits have been made.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_id=None):
        from writing.models import WorkingDocument

        # Get working document
        working_doc = get_object_or_404(
            WorkingDocument.objects.select_related('dispatch_content'),
            piece_id=piece_id,
            user=request.user,   # important: unique_together(piece, user)
        )

        # Check if collaborative
        if not working_doc.dispatch_content:
            return Response(
                {"error": "No collaboration to rescind"},
                status=status.HTTP_400_BAD_REQUEST
            )

        dispatch_content = working_doc.dispatch_content

        # Check if can be rescinded
        if not dispatch_content.can_be_rescinded():
            return Response(
                {
                    "error": "Cannot rescind collaboration - other users have made edits",
                    "has_collaborative_edits": True
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Safe to rescind
        with transaction.atomic():
            # Unlink from working document
            working_doc.dispatch_content = None
            working_doc.save()

            # Delete the dispatch content (cascades to collaborators)
            dispatch_content.delete()

        return Response({
            "message": "Collaboration rescinded successfully"
        }, status=status.HTTP_200_OK)


class WorkingDocumentCollaborationStatusView(generics.RetrieveAPIView):
    """
    GET: Get collaboration status for a working document.
    Returns dispatch_content details if collaborative, or null if solo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_id=None):
        from writing.models import WorkingDocument
        from dispatch.api.serializers import DispatchContentSerializer

        print("Fetching collaboration status for Piece:", piece_id)

        # Get working document - first try user's own, then author's (for collaborators)
        working_doc = WorkingDocument.objects.select_related('dispatch_content').filter(
            piece_id=piece_id,
            user=request.user
        ).first()

        # If not found and user is a collaborator, get the author's working document
        if not working_doc:
            # Get the piece to check if user is a collaborator
            piece = get_object_or_404(WritingPiece, pk=piece_id)

            # User might be a collaborator - try to find the author's working document
            working_doc = WorkingDocument.objects.select_related('dispatch_content').filter(
                piece_id=piece_id,
                user=piece.author
            ).first()

            if not working_doc:
                return Response(
                    {"error": "Working document not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if user is actually a collaborator
            is_collaborator = (
                working_doc.dispatch_content and
                working_doc.dispatch_content.collaborators.filter(id=request.user.id).exists()
            )

            if not is_collaborator:
                # Group admins/stewards may also access collaboration status
                from groups.services.groups import GroupService
                piece_group = working_doc.piece.group
                if piece_group:
                    membership = GroupService.get_user_membership(piece_group, request.user)
                    if membership and (membership.is_admin() or membership.is_steward()):
                        is_collaborator = True

            if not is_collaborator:
                return Response(
                    {"error": "Not authorized"},
                    status=status.HTTP_403_FORBIDDEN
                )

        if working_doc.dispatch_content:
            serializer = DispatchContentSerializer(working_doc.dispatch_content)
            return Response({
                "is_collaborative": True,
                "dispatch_content": serializer.data
            })
        else:
            return Response({
                "is_collaborative": False,
                "dispatch_content": None
            })


class WorkingDocumentEligibleCollaboratorsView(generics.GenericAPIView):
    """
    GET: Fetch eligible collaborators for a working document.
    Returns group members who can collaborate (have manage_write or manage_dispatch permission).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_id=None):
        from writing.models import WorkingDocument, WritingPiece
        from groups.models import Group, GroupMembership
        from groups.api.serializers import GroupMembershipListSerializer
        from django.contrib.contenttypes.models import ContentType

        # Get working document - first try user's own, then author's (for collaborators)
        working_doc = WorkingDocument.objects.select_related('piece').filter(
            piece_id=piece_id,
            user=request.user
        ).first()

        # If not found, user might be a collaborator - try author's working document
        if not working_doc:
            piece = get_object_or_404(WritingPiece, pk=piece_id)
            working_doc = WorkingDocument.objects.select_related('piece').filter(
                piece_id=piece_id,
                user=piece.author
            ).first()

            if not working_doc:
                return Response(
                    {"error": "Working document not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Get the piece to determine the sponsor
        piece = working_doc.piece

        # Check if piece is sponsored by a group
        group_content_type = ContentType.objects.get_for_model(Group)
        if piece.sponsor_content_type != group_content_type:
            # Not a group-sponsored piece, no eligible collaborators
            return Response({
                "eligible_collaborators": [],
                "message": "Only group-sponsored documents support collaboration"
            })

        # Get the group
        try:
            group = Group.objects.get(id=piece.sponsor_object_id, is_active=True)
        except Group.DoesNotExist:
            return Response(
                {"error": "Group not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get all active group members with collaboration-relevant permissions,
        # excluding the current user. Support both legacy role-based access and
        # the newer membership-decorator permission model.
        from django.db.models import Q

        eligible_memberships = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            is_pending=False
        ).filter(
            Q(roles__contains=['admin']) |
            Q(roles__contains=['steward']) |
            Q(
                decorator_links__enabled=True,
                decorator_links__decorator__code__in=[
                    'can__ManageWriting',
                    'can__ManageDispatch',
                ],
            )
        ).exclude(
            member_object_id=request.user.id
        ).select_related(
            'member_content_type'
        ).prefetch_related(
            'member_object'
        ).distinct()

        # Serialize the eligible members
        serializer = GroupMembershipListSerializer(eligible_memberships, many=True)

        return Response({
            "eligible_collaborators": serializer.data,
            "group_slug": group.slug,
            "group_name": group.title
        })


# ============================================================================
# Tag Management for WritingPiece
# ============================================================================

class WritingPieceTagsView(generics.GenericAPIView):
    """
    GET: Retrieve all tags for a writing piece
    PUT: Replace all tags for a writing piece
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        """Get all tags for a writing piece"""
        from classifications.models import Tag, ClassificationUsage
        from classifications.api.serializers import TagSerializer

        piece = get_object_or_404(
            WritingPiece.objects.select_related('sponsor_content_type'),
            pk=pk
        )

        # Get all tags for this piece
        tag_ct = ContentType.objects.get_for_model(Tag)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)

        tag_ids = ClassificationUsage.objects.filter(
            classification_client_content_type=piece_ct,
            classification_client_object_id=str(piece.pk),
            classification_content_type=tag_ct
        ).values_list('classification_object_id', flat=True)

        tags = Tag.objects.filter(id__in=tag_ids).order_by('title')
        serializer = TagSerializer(tags, many=True)
        return Response(serializer.data)

    def put(self, request, pk=None):
        """Replace all tags for a writing piece"""
        from classifications.models import Tag, ClassificationUsage

        piece = get_object_or_404(
            WritingPiece.objects.select_related('sponsor_content_type'),
            pk=pk
        )

        if not (
            request.user.is_staff or piece.author_id == request.user.id
            or can_edit_others_group_writing(request.user, piece)
        ):
            return Response(
                {"error": "Not authorized to edit tags"},
                status=status.HTTP_403_FORBIDDEN
            )

        tag_ids = request.data.get('tag_ids', [])

        if not isinstance(tag_ids, list):
            return Response(
                {"error": "tag_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate tag IDs exist
        tags = Tag.objects.filter(id__in=tag_ids)
        if len(tags) != len(tag_ids):
            return Response(
                {"error": "One or more tag IDs are invalid"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Remove all existing tags
            tag_ct = ContentType.objects.get_for_model(Tag)
            piece_ct = ContentType.objects.get_for_model(WritingPiece)

            old_usage = ClassificationUsage.objects.filter(
                classification_client_content_type=piece_ct,
                classification_client_object_id=str(piece.pk),
                classification_content_type=tag_ct
            )

            # Decrement usage counts for removed tags
            old_tag_ids = list(old_usage.values_list('classification_object_id', flat=True))
            old_usage.delete()

            for tag_id in old_tag_ids:
                Tag.objects.filter(id=tag_id).update(
                    usage_count=F('usage_count') - 1
                )

            # Add new tags
            for tag in tags:
                piece.add_classification(tag)

        # Return updated tags
        from classifications.api.serializers import TagSerializer
        updated_tags = Tag.objects.filter(id__in=tag_ids).order_by('title')
        serializer = TagSerializer(updated_tags, many=True)
        return Response(serializer.data)


class WritingPieceCategoriesView(generics.GenericAPIView):
    """
    GET: Retrieve all categories for a writing piece
    PUT: Replace all categories for a writing piece
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        """Get all categories for a writing piece"""
        from classifications.models import Category, ClassificationUsage
        from classifications.api.serializers import CategorySerializer

        piece = get_object_or_404(
            WritingPiece.objects.select_related('sponsor_content_type'),
            pk=pk
        )

        # Get all categories for this piece
        cat_ct = ContentType.objects.get_for_model(Category)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)

        cat_ids = ClassificationUsage.objects.filter(
            classification_client_content_type=piece_ct,
            classification_client_object_id=str(piece.pk),
            classification_content_type=cat_ct
        ).values_list('classification_object_id', flat=True)

        categories = Category.objects.filter(id__in=cat_ids).order_by('title')
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)

    def put(self, request, pk=None):
        """Replace all categories for a writing piece"""
        from classifications.models import Category, ClassificationUsage

        piece = get_object_or_404(
            WritingPiece.objects.select_related('sponsor_content_type'),
            pk=pk
        )

        if not (
            request.user.is_staff or piece.author_id == request.user.id
            or can_edit_others_group_writing(request.user, piece)
        ):
            return Response(
                {"error": "Not authorized to edit categories"},
                status=status.HTTP_403_FORBIDDEN
            )

        category_ids = request.data.get('category_ids', [])

        if not isinstance(category_ids, list):
            return Response(
                {"error": "category_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate category IDs exist
        categories = Category.objects.filter(id__in=category_ids)
        if len(categories) != len(category_ids):
            return Response(
                {"error": "One or more category IDs are invalid"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Remove all existing categories
            cat_ct = ContentType.objects.get_for_model(Category)
            piece_ct = ContentType.objects.get_for_model(WritingPiece)

            old_usage = ClassificationUsage.objects.filter(
                classification_client_content_type=piece_ct,
                classification_client_object_id=str(piece.pk),
                classification_content_type=cat_ct
            )

            # Decrement usage counts for removed categories
            old_cat_ids = list(old_usage.values_list('classification_object_id', flat=True))
            old_usage.delete()

            for cat_id in old_cat_ids:
                Category.objects.filter(id=cat_id).update(
                    usage_count=F('usage_count') - 1
                )

            # Add new categories
            for category in categories:
                piece.add_classification(category)

        # Return updated categories
        from classifications.api.serializers import CategorySerializer
        updated_categories = Category.objects.filter(id__in=category_ids).order_by('title')
        serializer = CategorySerializer(updated_categories, many=True)
        return Response(serializer.data)


# ============================================================================
# DOCX Import (Preview + Confirm)
# ============================================================================

import hashlib


def _normalize_existing_import(receipt):
    if not receipt:
        return None
    return {
        "piece_id": str(receipt.created_writing_piece_id),
        "receipt_id": str(receipt.id),
        "imported_at": receipt.created_at.isoformat(),
    }


def _resolve_import_sponsor(sponsor_type, sponsor_id=None, sponsor_slug=None):
    sponsor_type_normalized = (sponsor_type or "").lower()

    if sponsor_type_normalized == "group":
        sponsor = Group.objects.filter(slug=sponsor_slug).first() if sponsor_slug else Group.objects.filter(pk=sponsor_id).first()
        if not sponsor:
            raise ValidationError(f"Group sponsor not found: {sponsor_slug or sponsor_id}")
        return sponsor

    if sponsor_type_normalized in {"member", "user", "customuser"}:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        sponsor = User.objects.filter(username=sponsor_slug).first() if sponsor_slug else User.objects.filter(pk=sponsor_id).first()
        if not sponsor:
            raise ValidationError(f"Member sponsor not found: {sponsor_slug or sponsor_id}")
        return sponsor

    raise ValidationError(f"Unknown sponsor type: {sponsor_type}")


def _user_can_import_to_sponsor(user, sponsor) -> bool:
    if isinstance(sponsor, Group):
        return PermissionService.can_user_perform_action(user, "edit_writing", group_slug=sponsor.slug)
    return sponsor.id == user.id or getattr(user, "is_staff", False)


def _receipt_matches_sponsor(receipt, sponsor) -> bool:
    if not receipt or not sponsor:
        return False
    piece = receipt.created_writing_piece
    sponsor_ct = ContentType.objects.get_for_model(type(sponsor))
    return (
        piece.sponsor_content_type_id == sponsor_ct.id
        and str(piece.sponsor_object_id) == str(sponsor.id)
    )


def _find_existing_receipt_for_sponsor(file_sha256, sponsor):
    from writing.models import ImportReceipt

    receipts = ImportReceipt.objects.filter(source_sha256=file_sha256).select_related("created_writing_piece")
    for receipt in receipts:
        if _receipt_matches_sponsor(receipt, sponsor):
            return receipt
    return None


def _preview_docx_file(file_bytes, original_filename, file_sha256, sponsor):
    from writing.models import ImportReceipt
    from writing.importers.docx_to_tiptap import (
        docx_to_tiptap,
        extract_title,
        count_nodes_by_type,
    )
    from writing.importers.docx_comments import extract_docx_comments

    existing = _find_existing_receipt_for_sponsor(file_sha256, sponsor)

    body_json = docx_to_tiptap(file_bytes)
    title = extract_title(body_json) or original_filename.rsplit(".", 1)[0]
    node_counts = count_nodes_by_type(body_json)

    import os
    import tempfile

    comments = []
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        comments = extract_docx_comments(tmp_path)
    except Exception:
        comments = []
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    metadata_notes = {}
    if comments:
        metadata_notes["docx_comments"] = comments

    warnings = []
    if existing:
        warnings.append("This file hash has already been imported.")

    return {
        "file_type": "docx",
        "original_filename": original_filename,
        "file_sha256": file_sha256,
        "title": title,
        "excerpt": "",
        "body_json": body_json,
        "writing_kind": "dispatch",
        "addressed_to": "public",
        "enable_outline": False,
        "frontmatter": {},
        "metadata_notes": metadata_notes,
        "already_imported": bool(existing),
        "existing_import": _normalize_existing_import(existing),
        "warnings": warnings,
        "stats": {
            "word_count": 0,
            "heading_count": node_counts.get("heading", 0),
            "node_counts": node_counts,
            "comment_count": len(comments),
        },
    }


def _preview_markdown_file(file_bytes, original_filename, file_sha256, sponsor):
    from writing.importers.docx_to_tiptap import count_nodes_by_type
    from writing.importers.markdown_to_tiptap import parse_markdown_file

    parsed = parse_markdown_file(file_bytes, filename=original_filename)
    existing = _find_existing_receipt_for_sponsor(file_sha256, sponsor)
    frontmatter = parsed["frontmatter"]
    node_counts = count_nodes_by_type(parsed["body_json"])
    heading_count = node_counts.get("heading", 0)
    word_count = len(parsed["body_markdown"].split())

    warnings = list(parsed["warnings"])
    if existing:
        warnings.append("This file hash has already been imported.")

    # stage gate: warn if not "canon" (pre-import check only; not stored)
    stage = frontmatter.get("stage") or ""
    if stage and stage != "canon":
        warnings.append(
            f"stage is '{stage}' — only 'canon' articles are ready for import. "
            "Proceeding will create a draft."
        )

    # Promote series fields from frontmatter to top-level so confirm items carry them
    phase_num = frontmatter.get("phase")  # `phase: 0` in frontmatter
    series_order = frontmatter.get("series_order")

    _KNOWN_FRONTMATTER = {
        "title", "summary", "writing_kind", "addressed_to", "enable_outline",
        "tags", "slug", "source_url", "excerpt",
        # series / calendar fields — handled explicitly, not unmapped
        "phase", "series_order", "article_id", "stage", "synopsis",
        "created", "updated",
    }

    return {
        "file_type": "md",
        "original_filename": original_filename,
        "file_sha256": file_sha256,
        "title": parsed["title"],
        "excerpt": parsed["excerpt"],
        "body_json": parsed["body_json"],
        "writing_kind": frontmatter.get("writing_kind") or "article",
        "addressed_to": frontmatter.get("addressed_to") or "public",
        "enable_outline": bool(frontmatter.get("enable_outline", True)),
        "source_url": frontmatter.get("source_url") or "",
        "phase_num": phase_num,
        "series_order": series_order,
        "frontmatter": frontmatter,
        "metadata_notes": {
            "article_id": frontmatter.get("article_id"),  # audit only
            "stage": stage or None,
            "unmapped_frontmatter": {
                key: value
                for key, value in frontmatter.items()
                if key not in _KNOWN_FRONTMATTER
            },
        },
        "already_imported": bool(existing),
        "existing_import": _normalize_existing_import(existing),
        "warnings": warnings,
        "stats": {
            "word_count": word_count,
            "heading_count": heading_count,
            "node_counts": node_counts,
            "comment_count": 0,
        },
    }


def _resolve_series(series_id, phase_num, sponsor):
    """
    Resolve a WritingSeries by UUID or phase_num.
    sponsor is used to scope phase_num lookups to the right group.
    Returns None if nothing matches (not found, not an error by itself).
    """
    if series_id:
        try:
            return WritingSeries.objects.get(pk=series_id)
        except WritingSeries.DoesNotExist:
            return None
    if phase_num is not None:
        group = sponsor if hasattr(sponsor, "writing_series") else None
        qs = WritingSeries.objects.filter(phase_num=int(phase_num))
        if group:
            qs = qs.filter(group=group)
        return qs.first()
    return None


def _create_or_replace_imported_piece(
    *,
    request,
    sponsor,
    source_type,
    body_json,
    title,
    excerpt,
    writing_kind,
    addressed_to,
    enable_outline,
    source_url,
    file_sha256,
    original_filename,
    import_notes,
    replace_existing=False,
    series=None,
    series_order=None,
):
    from writing.importers.docx_to_tiptap import generate_outline_from_headings
    from writing.models import ImportReceipt

    outline_specs = generate_outline_from_headings(body_json) if enable_outline else []
    existing_receipt = _find_existing_receipt_for_sponsor(file_sha256, sponsor) if file_sha256 else None

    if replace_existing and existing_receipt:
        piece = existing_receipt.created_writing_piece
        with transaction.atomic():
            piece.body_json = body_json
            piece.title = title
            piece.excerpt = excerpt
            piece.writing_kind = writing_kind
            piece.addressed_to = addressed_to
            piece.enable_outline = enable_outline
            update_fields = [
                "body_json", "title", "excerpt", "writing_kind",
                "addressed_to", "enable_outline", "updated_at",
            ]
            if series is not None:
                piece.series = series
                piece.series_order = series_order
                update_fields += ["series", "series_order"]
            piece.save(update_fields=update_fields)

            if piece.status == "published":
                piece.create_version(content_changed=True)

            working_document, created = WorkingDocument.objects.get_or_create(
                piece=piece,
                user=request.user,
                defaults={
                    "title": title,
                    "excerpt": excerpt,
                    "body_json": body_json,
                },
            )
            if not created:
                working_document.title = title
                working_document.excerpt = excerpt
                working_document.body_json = body_json
                working_document.save(update_fields=["title", "excerpt", "body_json", "updated_at"])
            notes = existing_receipt.import_notes or {}
            replacements = notes.get("replacements", [])
            replacements.append(
                {
                    "replaced_at": timezone.now().isoformat(),
                    "replaced_by": str(request.user.id),
                    "source_type": source_type,
                }
            )
            notes["replacements"] = replacements
            notes.update(import_notes or {})
            existing_receipt.import_notes = notes
            existing_receipt.original_filename = original_filename
            existing_receipt.source_type = source_type
            existing_receipt.source_url = source_url or existing_receipt.source_url
            existing_receipt.save(
                update_fields=["import_notes", "original_filename", "source_type", "source_url", "updated_at"]
            )

            if outline_specs:
                from dispatch.models import DispatchOutlineNode

                DispatchOutlineNode.objects.filter(writing_piece=piece).delete()
                for spec in outline_specs:
                    DispatchOutlineNode.objects.create(
                        writing_piece=piece,
                        title=spec["title"],
                        order_index=spec["order_index"],
                        anchor_target=spec["anchor_target"],
                    )

        return piece, working_document, "replaced", len(outline_specs)

    if existing_receipt and not replace_existing:
        return existing_receipt.created_writing_piece, None, "skipped_duplicate", 0

    with transaction.atomic():
        piece = WritingPiece(
            author=request.user,
            title=title,
            excerpt=excerpt,
            body_json=body_json,
            writing_kind=writing_kind,
            addressed_to=addressed_to,
            enable_outline=enable_outline,
            series=series,
            series_order=series_order,
        )
        piece.set_sponsor(sponsor)
        piece.save()

        working_document = WorkingDocument.objects.create(
            piece=piece,
            user=request.user,
            title=title,
            excerpt=excerpt,
            body_json=body_json,
        )
        from writing.models import ImportReceipt

        ImportReceipt.objects.create(
            source_type=source_type,
            source_sha256=file_sha256,
            original_filename=original_filename,
            source_url=source_url,
            created_writing_piece=piece,
            imported_by=request.user,
            import_notes=import_notes or {},
        )

        if outline_specs:
            from dispatch.models import DispatchOutlineNode

            for spec in outline_specs:
                DispatchOutlineNode.objects.create(
                    writing_piece=piece,
                    title=spec["title"],
                    order_index=spec["order_index"],
                    anchor_target=spec["anchor_target"],
                )

    return piece, working_document, "created", len(outline_specs)


class DocxPreviewView(APIView):
    """
    POST /api/writing/import/preview

    Accepts a .docx file upload, parses it to TipTap JSON, and returns
    the preview data without creating any database records.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"error": "No file provided. Send a .docx file as 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not uploaded_file.name.lower().endswith(".docx"):
            return Response(
                {"error": f"Expected .docx file, got: {uploaded_file.name}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_bytes = uploaded_file.read()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Check idempotency
        from writing.models import ImportReceipt
        existing = ImportReceipt.objects.filter(source_sha256=file_sha256).first()
        already_imported = None
        if existing:
            already_imported = {
                "piece_id": str(existing.created_writing_piece_id),
                "receipt_id": str(existing.id),
                "imported_at": existing.created_at.isoformat(),
            }

        # Parse
        from writing.importers.docx_to_tiptap import (
            docx_to_tiptap,
            extract_title,
            count_nodes_by_type,
        )
        from writing.importers.docx_comments import extract_docx_comments

        try:
            body_json = docx_to_tiptap(file_bytes)
        except Exception as e:
            return Response(
                {"error": f"Failed to parse .docx: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        title = extract_title(body_json)
        node_counts = count_nodes_by_type(body_json)

        # Comments require a file path — write to temp file
        import tempfile, os
        comments = []
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            comments = extract_docx_comments(tmp_path)
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        return Response({
            "body_json": body_json,
            "title": title,
            "stats": {
                "node_counts": node_counts,
                "comment_count": len(comments),
            },
            "comments": comments,
            "file_sha256": file_sha256,
            "original_filename": uploaded_file.name,
            "already_imported": already_imported,
        })


class DocxImportView(APIView):
    """
    POST /api/writing/import/confirm

    Creates a WritingPiece from previously previewed TipTap JSON.
    Expects JSON body with body_json, title, sponsor info, etc.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        body_json = request.data.get("body_json")
        title = request.data.get("title", "").strip()
        writing_kind = request.data.get("writing_kind", "dispatch")
        sponsor_type = request.data.get("sponsor_type")
        sponsor_id = request.data.get("sponsor_id")
        enable_outline = request.data.get("enable_outline", False)
        source_url = request.data.get("source_url") or None
        file_sha256 = request.data.get("file_sha256", "")
        original_filename = request.data.get("original_filename", "")
        addressed_to = request.data.get("addressed_to", "public")
        force = request.data.get("force", False)
        mode = request.data.get("mode", "new")  # "new" or "replace"

        # Validate required fields
        if not body_json:
            return Response({"error": "body_json is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "title is required"}, status=status.HTTP_400_BAD_REQUEST)

        from writing.models import ImportReceipt

        # ── Replace mode: update existing piece in place ──
        if mode == "replace":
            if not file_sha256:
                return Response({"error": "file_sha256 is required for replace mode"}, status=status.HTTP_400_BAD_REQUEST)

            receipt = ImportReceipt.objects.filter(source_sha256=file_sha256).first()
            if not receipt:
                return Response({"error": "No previous import found for this file."}, status=status.HTTP_404_NOT_FOUND)

            piece = receipt.created_writing_piece

            # Optionally regenerate outline
            outline_specs = []
            if enable_outline:
                from writing.importers.docx_to_tiptap import generate_outline_from_headings
                outline_specs = generate_outline_from_headings(body_json)

            with transaction.atomic():
                # Update the piece
                piece.body_json = body_json
                piece.title = title
                piece.writing_kind = writing_kind
                piece.addressed_to = addressed_to
                piece.enable_outline = enable_outline
                piece.save(update_fields=[
                    "body_json", "title", "writing_kind", "addressed_to",
                    "enable_outline", "updated_at",
                ])

                # If published, create a version snapshot
                if piece.status == "published":
                    piece.create_version(content_changed=True)

                # Update or create working copy
                wc, created = WorkingDocument.objects.get_or_create(
                    piece=piece,
                    user=request.user,
                    defaults={"title": title, "body_json": body_json, "excerpt": ""},
                )
                if not created:
                    wc.title = title
                    wc.body_json = body_json
                    wc.save(update_fields=["title", "body_json", "updated_at"])

                # Update receipt notes
                notes = receipt.import_notes or {}
                replacements = notes.get("replacements", [])
                replacements.append({
                    "replaced_at": timezone.now().isoformat(),
                    "replaced_by": str(request.user.id),
                })
                notes["replacements"] = replacements
                receipt.import_notes = notes
                receipt.save(update_fields=["import_notes", "updated_at"])

                # Regenerate outline nodes if enabled
                outline_count = 0
                if outline_specs:
                    from dispatch.models import DispatchOutlineNode
                    DispatchOutlineNode.objects.filter(writing_piece=piece).delete()
                    for spec in outline_specs:
                        DispatchOutlineNode.objects.create(
                            writing_piece=piece,
                            title=spec["title"],
                            order_index=spec["order_index"],
                            anchor_target=spec["anchor_target"],
                        )
                    outline_count = len(outline_specs)

            serializer = WritingPieceSerializer(piece, context={"request": request})
            return Response({
                "piece": serializer.data,
                "outline_nodes_created": outline_count,
                "message": f'Replaced content of "{title}"',
            }, status=status.HTTP_200_OK)

        # ── New mode (default): create a new piece ──
        if not sponsor_type or not sponsor_id:
            return Response({"error": "sponsor_type and sponsor_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Idempotency check
        if file_sha256 and not force:
            existing = ImportReceipt.objects.filter(source_sha256=file_sha256).first()
            if existing:
                return Response({
                    "error": "This file has already been imported.",
                    "existing_piece_id": str(existing.created_writing_piece_id),
                    "receipt_id": str(existing.id),
                }, status=status.HTTP_409_CONFLICT)

        # Resolve sponsor
        try:
            ct = ContentType.objects.get(model=sponsor_type.lower())
        except ContentType.DoesNotExist:
            return Response({"error": f"Unknown sponsor type: {sponsor_type}"}, status=status.HTTP_400_BAD_REQUEST)
        except ContentType.MultipleObjectsReturned:
            ct = None
            for app in ["groups", "users", "identity"]:
                try:
                    ct = ContentType.objects.get(app_label=app, model=sponsor_type.lower())
                    break
                except ContentType.DoesNotExist:
                    continue
            if ct is None:
                return Response({"error": f"Ambiguous sponsor type: {sponsor_type}"}, status=status.HTTP_400_BAD_REQUEST)

        model_class = ct.model_class()
        try:
            sponsor = model_class.objects.get(pk=sponsor_id)
        except model_class.DoesNotExist:
            return Response({"error": f"{sponsor_type} with ID {sponsor_id} not found"}, status=status.HTTP_404_NOT_FOUND)

        # Optionally generate outline
        outline_specs = []
        if enable_outline:
            from writing.importers.docx_to_tiptap import generate_outline_from_headings
            outline_specs = generate_outline_from_headings(body_json)

        # Create records
        with transaction.atomic():
            piece = WritingPiece(
                author=request.user,
                title=title,
                body_json=body_json,
                writing_kind=writing_kind,
                addressed_to=addressed_to,
                enable_outline=enable_outline,
            )
            piece.set_sponsor(sponsor)
            piece.save()

            # Create working copy so the editor can load it and it appears in drafts
            WorkingDocument.objects.create(
                piece=piece,
                user=request.user,
                title=title,
                body_json=body_json,
                excerpt="",
            )

            # Import receipt
            import_notes = {"source": "web_import"}
            if outline_specs:
                import_notes["outline_count"] = len(outline_specs)

            ImportReceipt.objects.create(
                source_type="docx",
                source_sha256=file_sha256,
                original_filename=original_filename,
                source_url=source_url,
                created_writing_piece=piece,
                imported_by=request.user,
                import_notes=import_notes,
            )

            # Create outline nodes
            if outline_specs:
                from dispatch.models import DispatchOutlineNode
                for spec in outline_specs:
                    DispatchOutlineNode.objects.create(
                        writing_piece=piece,
                        title=spec["title"],
                        order_index=spec["order_index"],
                        anchor_target=spec["anchor_target"],
                    )

        serializer = WritingPieceSerializer(piece, context={"request": request})
        return Response({
            "piece": serializer.data,
            "outline_nodes_created": len(outline_specs),
            "message": f'Successfully imported "{title}"',  # noqa: E501
        }, status=status.HTTP_201_CREATED)


class DocumentImportBatchPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        sponsor_type = request.data.get("sponsor_type")
        sponsor_id = request.data.get("sponsor_id")
        sponsor_slug = request.data.get("sponsor_slug")

        if not sponsor_type or (not sponsor_id and not sponsor_slug):
            return Response(
                {"error": "sponsor_type and either sponsor_id or sponsor_slug are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            sponsor = _resolve_import_sponsor(sponsor_type, sponsor_id=sponsor_id, sponsor_slug=sponsor_slug)
        except ValidationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not _user_can_import_to_sponsor(request.user, sponsor):
            raise PermissionDenied("You do not have permission to import drafts for this sponsor.")

        uploaded_files = list(request.FILES.getlist("files"))
        if not uploaded_files:
            uploaded_files = list(request.FILES.getlist("files[]"))

        if not uploaded_files:
            return Response(
                {"error": "No files provided. Send one or more files as 'files'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = []
        for index, uploaded_file in enumerate(uploaded_files):
            original_filename = uploaded_file.name
            file_bytes = uploaded_file.read()
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()
            temp_id = f"tmp_{index + 1}"
            lower_name = original_filename.lower()

            try:
                if lower_name.endswith(".docx"):
                    preview = _preview_docx_file(file_bytes, original_filename, file_sha256, sponsor)
                elif lower_name.endswith(".md"):
                    preview = _preview_markdown_file(file_bytes, original_filename, file_sha256, sponsor)
                else:
                    items.append(
                        {
                            "temp_id": temp_id,
                            "original_filename": original_filename,
                            "file_type": "unknown",
                            "warnings": [f"Unsupported file type: {original_filename}"],
                            "error": f"Unsupported file type: {original_filename}",
                        }
                    )
                    continue
            except Exception as exc:  # noqa: BLE001
                items.append(
                    {
                        "temp_id": temp_id,
                        "original_filename": original_filename,
                        "file_type": "unknown",
                        "warnings": [str(exc)],
                        "error": f"Failed to parse {original_filename}: {exc}",
                    }
                )
                continue

            preview["temp_id"] = temp_id
            items.append(preview)

        return Response({"items": items}, status=status.HTTP_200_OK)


class DocumentImportBatchConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        sponsor_type = request.data.get("sponsor_type")
        sponsor_id = request.data.get("sponsor_id")
        sponsor_slug = request.data.get("sponsor_slug")
        items = request.data.get("items") or []

        if not sponsor_type or (not sponsor_id and not sponsor_slug):
            return Response(
                {"error": "sponsor_type and either sponsor_id or sponsor_slug are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(items, list) or not items:
            return Response(
                {"error": "items must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            sponsor = _resolve_import_sponsor(sponsor_type, sponsor_id=sponsor_id, sponsor_slug=sponsor_slug)
        except ValidationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not _user_can_import_to_sponsor(request.user, sponsor):
            raise PermissionDenied("You do not have permission to import drafts for this sponsor.")

        # Optional batch-level series resolution: by UUID (series_id) or phase number (phase_num)
        # Items can also carry their own phase_num (from frontmatter), which overrides the batch default.
        batch_series_obj = _resolve_series(
            request.data.get("series_id"),
            request.data.get("phase_num"),
            sponsor,
        )
        if request.data.get("series_id") and batch_series_obj is None:
            return Response(
                {"error": f"series_id '{request.data.get('series_id')}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for item_index, item in enumerate(items):
            temp_id = item.get("temp_id")
            body_json = item.get("body_json")
            title = (item.get("title") or "").strip()
            excerpt = (item.get("excerpt") or "").strip()
            writing_kind = item.get("writing_kind") or "article"
            addressed_to = item.get("addressed_to") or "public"
            enable_outline = bool(item.get("enable_outline", False))
            source_url = item.get("source_url") or None
            file_sha256 = item.get("file_sha256") or ""
            original_filename = item.get("original_filename") or ""
            source_type = item.get("file_type") or ("md" if original_filename.lower().endswith(".md") else "docx")
            replace_existing = bool(item.get("replace_existing", False))
            import_notes = item.get("import_notes") or {}

            # Per-item series: phase_num (from frontmatter) or series_id, falls back to batch default
            item_phase_num = item.get("phase_num")
            item_series_id = item.get("series_id")
            if item_phase_num is not None or item_series_id:
                series_obj = _resolve_series(item_series_id, item_phase_num, sponsor)
                if series_obj is None:
                    results.append({
                        "temp_id": temp_id,
                        "status": "error",
                        "error": (
                            f"No WritingSeries found for phase_num={item_phase_num!r} "
                            f"in group '{getattr(sponsor, 'slug', sponsor)}'. "
                            "Run seed_writing_series before importing."
                        ),
                    })
                    continue
            else:
                series_obj = batch_series_obj
            series_order = item.get("series_order")
            if series_order is None and series_obj is not None:
                series_order = item_index  # auto-assign position within batch

            if not body_json or not title:
                results.append(
                    {
                        "temp_id": temp_id,
                        "status": "error",
                        "error": "title and body_json are required for each item",
                    }
                )
                continue

            try:
                piece, working_document, result_status, outline_count = _create_or_replace_imported_piece(
                    request=request,
                    sponsor=sponsor,
                    source_type=source_type,
                    body_json=body_json,
                    title=title,
                    excerpt=excerpt,
                    writing_kind=writing_kind,
                    addressed_to=addressed_to,
                    enable_outline=enable_outline,
                    source_url=source_url,
                    file_sha256=file_sha256,
                    original_filename=original_filename,
                    import_notes=import_notes,
                    replace_existing=replace_existing,
                    series=series_obj,
                    series_order=series_order,
                )
                result = {
                    "temp_id": temp_id,
                    "status": result_status,
                    "piece": {
                        "id": str(piece.id),
                        "slug": piece.slug,
                        "status": piece.status,
                        "title": piece.title,
                    },
                    "outline_nodes_created": outline_count,
                }
                if working_document:
                    result["working_document"] = {"id": str(working_document.id)}
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "temp_id": temp_id,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        return Response({"results": results}, status=status.HTTP_200_OK)


# ==============================================================================
# Group writing catalog
# ==============================================================================

class GroupWritingCatalogView(generics.GenericAPIView):
    """
    GET /api/writing/catalog?group=<slug>

    Returns all published pieces for a group, ordered by series (phase_num)
    then series_order, for catalog rendering. No body_json — use the detail
    endpoint when opening a piece.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from writing.api.serializers import WritingPieceCatalogSerializer
        group_slug = request.query_params.get("group")
        if not group_slug:
            return Response({"error": "group query param required"}, status=status.HTTP_400_BAD_REQUEST)

        group = get_object_or_404(Group, slug=group_slug)
        ct = ContentType.objects.get_for_model(group)

        pieces = (
            WritingPiece.objects
            .filter(
                status="published",
                sponsor_content_type=ct,
                sponsor_object_id=group.id,
            )
            .select_related("author", "series")
            .order_by(
                "series__phase_num",
                "series_order",
                "-published_at",
            )
        )

        return Response(WritingPieceCatalogSerializer(pieces, many=True).data)


# ==============================================================================
# WritingSynopsis views
# ==============================================================================

class WritingSynopsisView(generics.GenericAPIView):
    """
    GET  /api/writing/pieces/<pk>/synopsis  — retrieve (auto-creates if missing)
    PATCH /api/writing/pieces/<pk>/synopsis — update editable fields
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_piece(self, pk, user):
        piece = get_object_or_404(WritingPiece, pk=pk)
        if piece.author != user and not user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied
        return piece

    def get(self, request, pk):
        from writing.api.serializers import WritingSynopsisSerializer
        piece = self._get_piece(pk, request.user)
        synopsis = getattr(piece, "synopsis", None)
        if synopsis is None:
            if piece.is_published:
                from writing.synopsis_service import SynopsisGenerationService
                synopsis = SynopsisGenerationService.generate_for_piece(piece)
            if synopsis is None:
                return Response({"detail": "No synopsis available yet."}, status=status.HTTP_404_NOT_FOUND)
        return Response(WritingSynopsisSerializer(synopsis).data)

    def patch(self, request, pk):
        from writing.api.serializers import WritingSynopsisSerializer
        piece = self._get_piece(pk, request.user)
        synopsis = getattr(piece, "synopsis", None)
        if synopsis is None:
            return Response({"detail": "No synopsis found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WritingSynopsisSerializer(synopsis, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WritingSynopsisRegenerateView(generics.GenericAPIView):
    """POST /api/writing/pieces/<pk>/synopsis/regenerate"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from writing.api.serializers import WritingSynopsisSerializer
        from writing.synopsis_service import SynopsisGenerationService
        piece = get_object_or_404(WritingPiece, pk=pk)
        if piece.author != request.user and not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied
        synopsis = SynopsisGenerationService.generate_for_piece(piece)
        if synopsis is None:
            return Response(
                {"detail": "Synopsis generation failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(WritingSynopsisSerializer(synopsis).data)


# ==============================================================================
# WritingSeries views
# ==============================================================================

class WritingSeriesListView(generics.GenericAPIView):
    """
    GET /api/writing/series?group=<slug>   — series for a group
    GET /api/writing/series?member=<slug>  — series for a member (by username)
    POST /api/writing/series               — create (group: admin/owner only; member: self only)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from writing.api.serializers import WritingSeriesSerializer
        from django.contrib.auth import get_user_model
        User = get_user_model()
        group_slug = request.query_params.get("group")
        member_slug = request.query_params.get("member")
        if group_slug:
            group = get_object_or_404(Group, slug=group_slug)
            qs = WritingSeries.objects.filter(group=group)
        elif member_slug:
            member = get_object_or_404(User, username=member_slug)
            qs = WritingSeries.objects.filter(user=member)
        else:
            qs = WritingSeries.objects.filter(group__isnull=True, user__isnull=True)
        return Response(WritingSeriesSerializer(qs, many=True).data)

    def post(self, request):
        from writing.api.serializers import WritingSeriesSerializer
        serializer = WritingSeriesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.validated_data.get("group")
        user = serializer.validated_data.get("user")
        if group:
            roles = PermissionService.get_user_roles_in_group(request.user, group.slug)
            if not any(r in roles for r in ["owner", "admin"]):
                raise PermissionDenied("Only group owners/admins can create series.")
        elif user:
            if user != request.user:
                raise PermissionDenied("You can only create series for yourself.")
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WritingPieceExecuteSplitView(generics.GenericAPIView):
    """
    POST /api/writing/pieces/<pk>/execute-split

    Reads confirmed splitMarker nodes from the user's WorkingDocument,
    creates new WritingPiece(s), and opens a WorkSession ready for
    stream authoring. No AI involved — purely deterministic.

    Response:
      {
        "session_id": "<uuid>",
        "surface_body_json": { ...TipTap doc with segmentBoundary nodes... },
        "new_piece_ids": ["<uuid>", ...]
      }
    """
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def post(self, request, pk):
        from writing.split_service import SplitError, execute_split

        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(request, piece)

        try:
            session = execute_split(piece, request.user)
        except SplitError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        new_piece_ids = [
            str(item.object_id)
            for item in session.items.order_by("sequence")
        ]

        return Response(
            {
                "session_id": str(session.pk),
                "surface_body_json": session.surface_document.body_json,
                "new_piece_ids": new_piece_ids,
            },
            status=status.HTTP_201_CREATED,
        )


class WritingPieceImageUploadView(APIView):
    """
    Upload an inline image for a writing piece.

    POST /api/writing/pieces/<uuid:pk>/upload-image  (multipart, field "image")

    Saves the image to Stash, creates a StoredFile record, and returns a
    *stable* serve URL (/api/files/<id>/serve) that the editor embeds in the
    piece's body_json. The serve endpoint presigns on each request, so the
    stored URL never expires. Requires edit permission on the piece (group
    edit_writing for group-sponsored pieces, ownership for member-sponsored).
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [FormParser, MultiPartParser]

    def post(self, request, pk):
        piece = get_object_or_404(WritingPiece, pk=pk)

        if not _user_can_import_to_sponsor(request.user, piece.sponsor):
            return Response(
                {"detail": "You do not have permission to edit this piece."},
                status=status.HTTP_403_FORBIDDEN,
            )

        image = request.FILES.get("image")
        if not image:
            return Response(
                {"detail": "No image file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if image.size > MAX_INLINE_IMAGE_BYTES:
            return Response(
                {"detail": f"Image too large (max {MAX_INLINE_IMAGE_BYTES // (1024 * 1024)}MB)."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        content_type = (image.content_type or "").lower()
        if content_type not in ALLOWED_INLINE_IMAGE_MIME:
            return Response(
                {"detail": f"Unsupported image type: {content_type or 'unknown'}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base = get_valid_filename(image.name or "")
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())
        s3_key = f"writing/images/{piece.pk}/{unique}"

        image.seek(0)
        saved_key = default_storage.save(s3_key, image)

        stored = StoredFile.objects.create(
            file_path=saved_key,
            file_name=image.name or "",
            file_type=image.content_type or "",
            file_size=image.size or 0,
            uploaded_by=request.user,
            source="writing-inline",
        )

        return Response(
            {
                "id": str(stored.pk),
                "serve_url": f"/api/files/{stored.pk}/serve",
            },
            status=status.HTTP_201_CREATED,
        )
