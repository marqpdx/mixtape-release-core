# api/writing/views.py








# apps/content/views.py
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Length, Trim
from django.shortcuts import get_object_or_404
from django.utils import dateparse
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from writing.api.permissions import IsAuthorOrStaff
from writing.models import (
    Seed,
    WritingComment,
    WritingPiece,
    WritingPlacement,
    WritingWorkingCopy,
)
from writing.services import promote_seed_to_working_copy

from ..models import WritingPiece, is_provisional_slug
from ..permissions import CanEditWritingPiece, CanPublishWritingPiece
from .serializers import (
    SeedSerializer,
    SeedUpdateSerializer,
    WritingCommentSerializer,
    WritingPieceDetailSerializer,
    WritingPieceSerializer,
    WritingPlacementSerializer,
    WritingWorkingCopyLightSerializer,
)


class WritingWorkingCopyUpsertView(generics.GenericAPIView):
    """
    PUT: Upsert the working copy for the current user.
    GET: (optional) Return current working copy if exists.
    """
    serializer_class = WritingWorkingCopyLightSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def get_piece(self, pk):
        piece = get_object_or_404(WritingPiece, pk=pk, author=self.request.user)
        self.check_object_permissions(self.request, piece)
        return piece

    def get(self, request, pk=None):
        piece = self.get_piece(pk)
        wc = WritingWorkingCopy.objects.filter(piece=piece, user=request.user).first()
        if not wc:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(wc).data)

    def put(self, request, pk=None):
        piece = self.get_piece(pk)
        wc, _ = WritingWorkingCopy.objects.get_or_create(piece=piece, user=request.user)
        ser = self.get_serializer(instance=wc, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        wc = ser.save()
        WritingWorkingCopy.objects.filter(pk=wc.pk).update(auto_save_count=F("auto_save_count") + 1)
        wc.refresh_from_db()
        return Response(self.get_serializer(wc).data, status=status.HTTP_200_OK)


class WritingWorkingCopyApplyView(generics.GenericAPIView):
    """
    POST: Merge the user's working copy into the canonical piece and snapshot if published.
    """
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def post(self, request, pk=None):
        piece = get_object_or_404(WritingPiece, pk=pk, author=request.user)
        self.check_object_permissions(request, piece)

        wc = get_object_or_404(WritingWorkingCopy, piece=piece, user=request.user)
        changed = wc.apply_to_piece(piece)
        if changed and piece.is_published:
            piece.create_version(content_changed=True)
        return Response(self.get_serializer(piece).data, status=status.HTTP_200_OK)


class WritingPieceListCreateView(generics.ListCreateAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = WritingPiece.objects.filter(author=self.request.user)

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
            "placements",
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
                working_copy = WritingWorkingCopy.objects.create(
                    piece=piece,
                    user=request.user,
                    title=piece.title,
                    body_json=piece.body_json,
                    excerpt=piece.excerpt,
                )

                # Add working copy to response
                working_copy_data = WritingWorkingCopyLightSerializer(working_copy).data
                response.data["working_copy"] = working_copy_data

        return response


class WritingPieceRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]
    lookup_field = "slug"

    def get_queryset(self):
        return WritingPiece.objects.filter(author=self.request.user)


class WritingPiecePublicView(generics.RetrieveAPIView):
    """
    Retrieve a single published WritingPiece by slug (sponsor-agnostic).
    Used for public viewing of published content.

    GET /api/writing/pieces/view/{slug}
    """
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.AllowAny]  # Visibility checks done in get_queryset
    lookup_field = "slug"

    def get_queryset(self):
        # Base queryset: published pieces only
        queryset = WritingPiece.objects.filter(
            status="published"
        ).select_related(
            "author",
            "sponsor_content_type"
        ).prefetch_related(
            "versions",
            "placements"
        )

        # TODO: Add visibility filtering based on placements if needed
        # For now, all published pieces are viewable
        # You can add logic here to check placement visibility

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Override to increment view count"""
        instance = self.get_object()
        instance.increment_view_count()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


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
        group = get_object_or_404(Group, slug=group_slug)

        # Base queryset: published pieces in this group's feed
        queryset = WritingPiece.objects.filter(
            placements__target_content_type=ContentType.objects.get_for_model(Group),
            placements__target_object_id=group.id,
            placements__channel="feed",
            status="published"
        ).select_related(
            "author",
            "author__profile",
            "sponsor_content_type"
        ).prefetch_related(
            "versions",
            "placements"
        ).distinct()

        # Visibility filtering
        user = self.request.user
        if user.is_authenticated and hasattr(group, "is_member") and group.is_member(user):
            # Members can see public + members-only
            queryset = queryset.filter(
                placements__visibility__in=["public", "members"]
            )
        else:
            # Public users can only see public pieces
            queryset = queryset.filter(placements__visibility="public")

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Override to increment view count"""
        instance = self.get_object()
        instance.increment_view_count()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


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

        wc = WritingWorkingCopy.objects.filter(piece=piece, user=request.user).first()
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
            qs = qs.annotate(tlen=Length(Trim("body_text"))).filter(tlen__gt=0)

        return qs.order_by("-updated_at")

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
        "lantern": false
      },

      // Defaults applied to all placements unless overridden per-target:
      "placement_options": {
        "visibility": "public",               // "public"|"members"|"private"|"scheduled"
        "follow_updates": true,               // if false, locks to a version
        "locked_version_no": 2,               // optional; will default to current_version_no if follow_updates=false
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
      }
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

    def _coerce_bool(self, v, default=False):
        if isinstance(v, bool): return v
        if isinstance(v, str): return v.lower() in ("1","true","yes","y","on")
        return default

    def post(self, request, pk=None):
        piece = self.get_piece(pk)

        # Safety check - don't allow publishing empty pieces
        if piece.is_empty:
            return Response({
                "error": "Cannot publish empty content"
            }, status=400)

        data = request.data or {}

        destinations = data.get("destinations", {}) or {}
        placement_defaults = data.get("placement_options", {}) or {}
        group_overrides = data.get("group_overrides", {}) or {}

        if not any([destinations.get("personal"), destinations.get("lantern"), destinations.get("groups")]):
            return Response({"error": "At least one destination must be selected."},
                            status=status.HTTP_400_BAD_REQUEST)

        # parse schedule
        scheduled_for = None
        if data.get("scheduled_for"):
            scheduled_for = dateparse.parse_datetime(data["scheduled_for"])
            if not scheduled_for:
                return Response({"error": "scheduled_for must be ISO8601 datetime."},
                                status=status.HTTP_400_BAD_REQUEST)

        # collect optional edits
        editable_fields = {}
        for fld in ("title", "excerpt", "canonical_url", "writing_kind", "body_json"):
            if fld in data:
                editable_fields[fld] = data[fld]

        # derive follow_updates default
        # prefer request default if provided, otherwise canonical-kind heuristic
        default_follow_updates = placement_defaults.get("follow_updates")
        if default_follow_updates is None:
            default_follow_updates = piece.is_canonical_kind

        try:
            with transaction.atomic():
                # merge payload edits
                if editable_fields:
                    if editable_fields.get("title") in (None, ""):
                        editable_fields["title"] = "Untitled"

                    piece.__dict__.update({k: v for k, v in editable_fields.items() if v is not None})

                    # ✅ Use single utility function
                    if "title" in editable_fields and is_provisional_slug(piece.slug):
                        piece.slug = None

                    piece.save(update_fields=list(editable_fields.keys()) + ["updated_at"])


                # merge working copy (if exists)
                wc = WritingWorkingCopy.objects.filter(piece=piece, user=request.user).first()
                if wc:
                    wc.apply_to_piece(piece)

                # tags
                if hasattr(piece, "tags") and isinstance(data.get("tags"), (list, tuple)):
                    piece.tags.set(data["tags"])

                # publish or schedule (this may create first version if publishing now)
                piece.publish(scheduled_for=scheduled_for)

                placements_created = 0

                # helper to compute placement kwargs
                def build_kwargs(base_opts, override_opts=None):
                    o = dict(base_opts or {})
                    o.update(override_opts or {})

                    # Normalize booleans
                    o["follow_updates"] = self._coerce_bool(o.get("follow_updates"), default_follow_updates)
                    o["is_excerpt"] = self._coerce_bool(o.get("is_excerpt"), False)
                    o["is_pinned"] = self._coerce_bool(o.get("is_pinned"), False)

                    # Lock version if not following updates
                    if o.get("follow_updates") is False:
                        if not o.get("locked_version_no"):
                            o["locked_version_no"] = piece.current_version_no or 1
                        # safety: ensure version exists
                        if not piece.versions.filter(version_no=o["locked_version_no"]).exists():
                            o["locked_version_no"] = piece.current_version_no or 1
                    else:
                        o["locked_version_no"] = None

                    # Visibility defaulting (respect scheduling)
                    if piece.status == "scheduled":
                        o["visibility"] = "scheduled"
                    elif not o.get("visibility"):
                        o["visibility"] = "public"

                    return o


                # PERSONAL
                if destinations.get("personal"):
                    ct_user = ContentType.objects.get_for_model(request.user.__class__)
                    opts = build_kwargs(placement_defaults)
                    opts = apply_teaser_override(opts, data.get("summary") or piece.excerpt or data.get("excerpt") or "")

                    placement, created = WritingPlacement.objects.update_or_create(
                        piece=piece,
                        target_content_type=ct_user,
                        target_object_id=str(request.user.id),
                        channel="feed",
                        defaults={
                            "visibility": opts.get("visibility", "public"),
                            "follow_updates": opts["follow_updates"],
                            "locked_version_no": opts.get("locked_version_no"),
                            "is_excerpt": opts.get("is_excerpt", False),
                            "fragment_selector": opts.get("fragment_selector"),
                            "overrides": opts.get("overrides"),
                            "order": int(opts.get("order") or 0),
                            "is_pinned": opts.get("is_pinned", False),
                        }
                    )
                    if created:
                        placements_created += 1

                # GROUPS
                group_idents = destinations.get("groups") or []
                if group_idents:
                    ct_group = ContentType.objects.get_for_model(Group)
                    for ident in group_idents:
                        # Resolve group by slug, then id
                        grp = None
                        try:
                            grp = Group.objects.get(slug=ident)
                        except Group.DoesNotExist:
                            try:
                                grp = Group.objects.get(id=ident)
                            except Group.DoesNotExist:
                                continue  # skip invalid entry

                        # Permission guard
                        if hasattr(grp, "can_user_post") and not grp.can_user_post(request.user):
                            continue

                        # per-group override
                        g_override = group_overrides.get(str(ident)) or group_overrides.get(str(grp.id)) or {}

                        opts = build_kwargs(placement_defaults, g_override)
                        opts = apply_teaser_override(opts, data.get("summary") or piece.excerpt or data.get("excerpt") or "")

                        _, created = WritingPlacement.objects.update_or_create(
                            piece=piece,
                            target_content_type=ct_group,
                            target_object_id=str(grp.id),
                            channel="feed",
                            defaults={
                                "visibility": opts.get("visibility", "public"),
                                "follow_updates": opts["follow_updates"],
                                "locked_version_no": opts.get("locked_version_no"),
                                "is_excerpt": opts.get("is_excerpt", False),
                                "fragment_selector": opts.get("fragment_selector"),
                                "overrides": opts.get("overrides"),
                                "order": int(opts.get("order") or 0),
                                "is_pinned": opts.get("is_pinned", False),
                            }
                        )
                        if created:
                            placements_created += 1

                # LANTERN
                if destinations.get("lantern"):
                    ct_user = ContentType.objects.get_for_model(request.user.__class__)
                    # auto-set a default lantern subject if not provided
                    overrides = (placement_defaults.get("overrides") or {}).copy()
                    overrides.setdefault(
                        "lantern_subject",
                        f"New from {request.user.get_full_name() or request.user.username}: {piece.title}"
                    )
                    opts = build_kwargs({**placement_defaults, "overrides": overrides})
                    opts = apply_teaser_override(opts, data.get("summary") or piece.excerpt or data.get("excerpt") or "")

                    _, created = WritingPlacement.objects.update_or_create(
                        piece=piece,
                        target_content_type=ct_user,
                        target_object_id=str(request.user.id),
                        channel="lantern",
                        defaults={
                            "visibility": opts.get("visibility", "public"),
                            "follow_updates": True,  # newsletters usually mirror latest
                            "locked_version_no": None,
                            "is_excerpt": opts.get("is_excerpt", False),
                            "fragment_selector": opts.get("fragment_selector"),
                            "overrides": opts.get("overrides"),
                            "order": int(opts.get("order") or 0),
                            "is_pinned": opts.get("is_pinned", False),
                        }
                    )
                    if created:
                        placements_created += 1

                serializer = self.get_serializer(piece, context={"request": request})
                msg_base = "scheduled" if scheduled_for else "published"
                placements = piece.placements.select_related().all()
                return Response({
                    "id": str(piece.id),
                    "piece": serializer.data,
                    "placements_created": placements_created,
                    "placements": WritingPlacementSerializer(placements, many=True, context={"request": request}).data,
                    "message": f'Successfully {msg_base} "{piece.title}" to {placements_created} destination(s).'
                }, status=status.HTTP_200_OK)
        except ValidationError as ve:
            return Response({"error": ve.message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # TODO: logger.exception("Publish & place failed", extra={...})
            return Response({"error": f"Publish & place failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    logger.info(f"🎯 clear_empty_flag called for piece_id: {piece_id}")
    piece = get_object_or_404(WritingPiece, id=piece_id)
    logger.info(f"📝 Found piece {piece.id}, is_empty={piece.is_empty}")

    # Use update() to bypass the save() method which auto-recalculates is_empty
    WritingPiece.objects.filter(id=piece_id).update(is_empty=False)

    # Verify it was saved
    piece.refresh_from_db()
    logger.info(f"✅ After update, is_empty={piece.is_empty}")

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

        # Get working document
        # working_doc = get_object_or_404(
        #     WorkingDocument.objects.select_related('dispatch_content'),
        #     pk=pk
        # )

        working_doc = get_object_or_404(
            WorkingDocument.objects.select_related('dispatch_content'),
            piece_id=piece_id,
            user=request.user,   # important: unique_together(piece, user)
        )

        # Check user has access (owner or collaborator)
        has_access = (
            working_doc.user == request.user or
            (working_doc.dispatch_content and
             working_doc.dispatch_content.collaborators.filter(id=request.user.id).exists())
        )

        if not has_access:
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

        # Check permissions (author or staff)
        if not (request.user.is_staff or piece.author == request.user):
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

        # Check permissions (author or staff)
        if not (request.user.is_staff or piece.author == request.user):
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
