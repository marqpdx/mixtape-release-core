# writing/api/views.py

from django.contrib.contenttypes.models import ContentType
import uuid
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from django.db import transaction
from django.db.models import F, Max, Q
from django.db.models.functions import Length, Trim
from django.shortcuts import get_object_or_404
from django.utils import dateparse, timezone
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.api.permissions import IsAuthorOrStaff
from files.models import StoredFile
from writing.models import (
    Seed,
    WritingComment,
    WritingPiece,
    # WritingPlacement,  # Deprecated - replaced by ContentPlacement
    WritingWorkingCopy,
)
from writing.services import promote_seed_to_working_copy
from writing.tasks import transcribe_seed_task

MAX_SEED_AUDIO_BYTES = 20 * 1024 * 1024  # 20MB
ALLOWED_AUDIO_PREFIXES = ("audio/",)
ALLOWED_AUDIO_MIME = ("video/webm",)

from ..models import WritingPiece, is_provisional_slug
from ..permissions import CanEditWritingPiece, CanPublishWritingPiece
from .serializers import (
    SeedSerializer,
    SeedUpdateSerializer,
    WritingCommentSerializer,
    WritingPieceDetailSerializer,
    WritingPieceSerializer,
    # WritingPlacementSerializer,  # Deprecated - replaced by ContentPlacement
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
        piece = get_object_or_404(WritingPiece, pk=pk)
        self.check_object_permissions(self.request, piece)
        return piece

    def get(self, request, pk=None):
        piece = self.get_piece(pk)

        # First try to find user's own working copy
        wc = WritingWorkingCopy.objects.filter(piece=piece, user=request.user).first()

        # If not found and piece is collaborative, find the author's working copy
        # (collaborators work on the same shared document via Yjs)
        if not wc and piece.author_id != request.user.id:
            wc = WritingWorkingCopy.objects.filter(piece=piece, user=piece.author).first()

        if not wc:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(wc).data)

    def put(self, request, pk=None):
        piece = self.get_piece(pk)

        # Try to find existing working copy for this user
        wc = WritingWorkingCopy.objects.filter(piece=piece, user=request.user).first()

        # If not found and user is not the author, they're a collaborator
        # Collaborators should update the author's working copy (shared document)
        if not wc and piece.author_id != request.user.id:
            wc = WritingWorkingCopy.objects.filter(piece=piece, user=piece.author).first()

        # If still no working copy exists, create one
        if not wc:
            wc = WritingWorkingCopy.objects.create(piece=piece, user=request.user)

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
                body_text="",
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
        audience = data.get("audience")
        addressed_to = data.get("addressed_to")

        has_destinations = any(
            [
                destinations.get("personal"),
                destinations.get("lantern"),
                destinations.get("groups"),
                destinations.get("shelves"),
            ]
        )
        if not has_destinations and audience != "just_me":
            return Response(
                {"error": "At least one destination must be selected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # parse schedule
        scheduled_for = None
        if data.get("scheduled_for"):
            scheduled_for = dateparse.parse_datetime(data["scheduled_for"])
            if not scheduled_for:
                return Response({"error": "scheduled_for must be ISO8601 datetime."},
                                status=status.HTTP_400_BAD_REQUEST)

        # collect optional edits
        editable_fields = {}
        for fld in ("title", "excerpt", "canonical_url", "writing_kind", "body_json", "addressed_to"):
            if fld in data:
                editable_fields[fld] = data[fld]

        # derive follow_updates default (v1: locked by default)
        default_follow_updates = placement_defaults.get("follow_updates")
        if default_follow_updates is None:
            default_follow_updates = False

        try:
            with transaction.atomic():
                # merge payload edits
                if editable_fields:
                    if editable_fields.get("title") in (None, ""):
                        editable_fields["title"] = "Untitled"

                    if "addressed_to" in editable_fields and not editable_fields["addressed_to"]:
                        editable_fields.pop("addressed_to")

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

                # addressed_to default (if not explicitly set)
                if not piece.addressed_to:
                    if audience == "just_me":
                        piece.addressed_to = WritingPiece.AddressedTo.SELF
                    elif audience == "readers":
                        piece.addressed_to = WritingPiece.AddressedTo.PUBLIC

                # publish or schedule (v1: create artifact first, then placements)
                if scheduled_for:
                    if not (piece.title or "").strip():
                        raise ValidationError("Please add a title before scheduling.")
                    piece.status = "scheduled"
                    piece.scheduled_for = scheduled_for
                    piece.save(update_fields=["status", "scheduled_for", "slug", "updated_at", "addressed_to"])
                else:
                    if not (piece.title or "").strip():
                        raise ValidationError("Please add a title before publishing.")
                    piece.status = "published"
                    piece.published_at = timezone.now()
                    piece.save(update_fields=["status", "published_at", "slug", "updated_at", "addressed_to"])

                # create immutable artifact (WritingVersion)
                from writing.models import WritingVersion
                next_sequence_no = (
                    WritingVersion.objects.filter(writing_piece=piece)
                    .aggregate(Max("sequence_no"))
                    .get("sequence_no__max") or 0
                ) + 1
                writing_version = WritingVersion.objects.create(
                    writing_piece=piece,
                    sequence_no=next_sequence_no,
                    version_label=str(next_sequence_no),
                    body_json=piece.body_json,
                    title=piece.title,
                    excerpt=piece.excerpt,
                    kind="release",
                    created_by=request.user,
                )
                piece.current_version_no = next_sequence_no
                piece.save(update_fields=["current_version_no", "updated_at"])

                # ==============================================================================
                # PLACEMENT CREATION (Phase 5)
                # ==============================================================================
                from publishing.models import PublicationGroup
                from publishing.serializers import ContentPlacementSerializer

                ct_piece = ContentType.objects.get_for_model(WritingPiece)
                pub_group = None

                def ensure_publication_group():
                    nonlocal pub_group
                    if pub_group is None:
                        pub_group = PublicationGroup.objects.create(
                            created_by=request.user,
                            source_content_type=ct_piece,
                            source_object_id=piece.id,
                            note=data.get("publish_note", ""),
                        )
                    return pub_group

                placements_created = 0
                placements = []

                # Helper to build placement kwargs
                def build_placement_kwargs(base_opts, override_opts=None):
                    """Build ContentPlacement defaults from options."""
                    opts = dict(base_opts or {})
                    opts.update(override_opts or {})

                    # Normalize booleans
                    follow_updates = self._coerce_bool(opts.get("follow_updates"), default_follow_updates)
                    is_excerpt = self._coerce_bool(opts.get("is_excerpt"), False)

                    # Determine visibility
                    if piece.status == "scheduled":
                        visibility = "scheduled"
                    else:
                        visibility = opts.get("visibility", "public")

                    # Locked artifact handling
                    locked_artifact_ct = None
                    locked_artifact_id = None
                    if not follow_updates:
                        locked_artifact_ct = ContentType.objects.get_for_model(writing_version.__class__)
                        locked_artifact_id = writing_version.id

                    return {
                        "follow_updates": follow_updates,
                        "locked_artifact_content_type": locked_artifact_ct,
                        "locked_artifact_object_id": locked_artifact_id,
                        "visibility": visibility,
                        "is_excerpt": is_excerpt,
                        "fragment_selector": opts.get("fragment_selector"),
                        "overrides": opts.get("overrides", {}),
                    }

                # PERSONAL FEED
                if destinations.get("personal"):
                    ct_user = ContentType.objects.get_for_model(request.user.__class__)
                    kwargs = build_placement_kwargs(placement_defaults)

                    # Apply excerpt override if provided
                    if data.get("summary") or piece.excerpt or data.get("excerpt"):
                        kwargs["overrides"]["excerpt"] = data.get("summary") or piece.excerpt or data.get("excerpt")

                    placement, created = ContentPlacement.objects.update_or_create(
                        source_content_type=ct_piece,
                        source_object_id=piece.id,
                        target_content_type=ct_user,
                        target_object_id=request.user.id,
                        channel="feed",
                        defaults={
                            "publication_group": ensure_publication_group(),
                            "placed_by": request.user,
                            **kwargs,
                        }
                    )
                    if created:
                        placements_created += 1
                    placements.append(placement)

                # GROUPS
                group_idents = destinations.get("groups") or []
                if group_idents:
                    from groups.models import Group
                    ct_group = ContentType.objects.get_for_model(Group)

                    for ident in group_idents:
                        # Resolve group by slug or id
                        grp = None
                        try:
                            grp = Group.objects.get(slug=ident)
                        except Group.DoesNotExist:
                            try:
                                grp = Group.objects.get(id=ident)
                            except Group.DoesNotExist:
                                continue

                        # Permission check
                        if hasattr(grp, "can_user_post") and not grp.can_user_post(request.user):
                            continue

                        # Per-group override
                        g_override = group_overrides.get(str(ident)) or group_overrides.get(str(grp.id)) or {}
                        kwargs = build_placement_kwargs(placement_defaults, g_override)

                        # Apply excerpt override
                        if data.get("summary") or piece.excerpt or data.get("excerpt"):
                            kwargs["overrides"]["excerpt"] = data.get("summary") or piece.excerpt or data.get("excerpt")

                        placement, created = ContentPlacement.objects.update_or_create(
                            source_content_type=ct_piece,
                            source_object_id=piece.id,
                            target_content_type=ct_group,
                            target_object_id=grp.id,
                            channel="feed",
                            defaults={
                                "publication_group": ensure_publication_group(),
                                "placed_by": request.user,
                                **kwargs,
                            }
                        )
                        if created:
                            placements_created += 1
                        placements.append(placement)

                # LANTERN (Newsletter)
                if destinations.get("lantern"):
                    ct_user = ContentType.objects.get_for_model(request.user.__class__)
                    kwargs = build_placement_kwargs(placement_defaults)

                    # Set lantern subject
                    overrides = kwargs.get("overrides", {}).copy()
                    if not overrides.get("lantern_subject"):
                        overrides["lantern_subject"] = f"New from {request.user.get_full_name() or request.user.username}: {piece.title}"
                    kwargs["overrides"] = overrides

                    # Apply excerpt override
                    if data.get("summary") or piece.excerpt or data.get("excerpt"):
                        kwargs["overrides"]["excerpt"] = data.get("summary") or piece.excerpt or data.get("excerpt")

                    placement, created = ContentPlacement.objects.update_or_create(
                        source_content_type=ct_piece,
                        source_object_id=piece.id,
                        target_content_type=ct_user,
                        target_object_id=request.user.id,
                        channel="lantern",
                        defaults={
                            "publication_group": ensure_publication_group(),
                            "placed_by": request.user,
                            **kwargs,
                        }
                    )
                    if created:
                        placements_created += 1
                    placements.append(placement)

                # SHELVES (Library placements)
                shelf_ids = destinations.get("shelves") or []
                if shelf_ids:
                    from stackroom.models import Library
                    ct_library = ContentType.objects.get_for_model(Library)
                    shelves = Library.objects.filter(id__in=shelf_ids)
                    for shelf in shelves:
                        next_order = (
                            ContentPlacement.objects.filter(
                                target_content_type=ct_library,
                                target_object_id=shelf.id,
                                channel="shelf",
                            ).aggregate(Max("order_index")).get("order_index__max") or 0
                        ) + 1
                        kwargs = build_placement_kwargs(placement_defaults)
                        if piece.status != "scheduled":
                            kwargs["visibility"] = shelf.visibility

                        if data.get("summary") or piece.excerpt or data.get("excerpt"):
                            kwargs["overrides"]["excerpt"] = data.get("summary") or piece.excerpt or data.get("excerpt")

                        placement, created = ContentPlacement.objects.update_or_create(
                            source_content_type=ct_piece,
                            source_object_id=piece.id,
                            target_content_type=ct_library,
                            target_object_id=shelf.id,
                            channel="shelf",
                            defaults={
                                "publication_group": ensure_publication_group(),
                                "placed_by": request.user,
                                "order_index": next_order,
                                **kwargs,
                            }
                        )
                        if created:
                            placements_created += 1
                        placements.append(placement)

                # Return response
                serializer = self.get_serializer(piece, context={"request": request})
                msg_base = "scheduled" if scheduled_for else "published"
                return Response({
                    "id": str(piece.id),
                    "piece": serializer.data,
                    "placements_created": placements_created,
                    "placements": ContentPlacementSerializer(placements, many=True, context={"request": request}).data,
                    "publication_group_id": str(pub_group.id) if pub_group else None,
                    "message": f'Successfully {msg_base} "{piece.title}" to {placements_created} destination(s).'
                }, status=status.HTTP_200_OK)
        except ValidationError as ve:
            return Response({"error": ve.message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # TODO: logger.exception("Publish & place failed", extra={...})
            return Response({"error": f"Publish & place failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        # Get all active group members with write permissions
        # excluding the current user (already a collaborator)
        # Members with 'admin' or 'steward' roles typically have write permissions
        from django.db.models import Q

        eligible_memberships = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            is_pending=False
        ).filter(
            # Filter for members with admin or steward roles
            # These roles typically have write/dispatch permissions
            Q(roles__contains=['admin']) |
            Q(roles__contains=['steward'])
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


# ============================================================================
# DOCX Import (Preview + Confirm)
# ============================================================================

import hashlib


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
                wc, created = WritingWorkingCopy.objects.get_or_create(
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
                    "replaced_by": request.user.id,
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
            WritingWorkingCopy.objects.create(
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
            "message": f'Successfully imported "{title}"',
        }, status=status.HTTP_201_CREATED)
