# writing/api/leaf_views.py

import uuid as uuid_mod

from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import StoredFile
from utils.shared.contenttypes import resolve_content_type
from writing.api.permissions import IsAuthorOrStaff
from writing.models import Leaf, Seed
from writing.services import (
    create_reference_leaf,
    promote_leaf_to_working_copy,
    promote_seed_to_leaf,
    quick_post_leaf,
    PromotionError,
)

from .serializers import (
    LeafCreateSerializer,
    LeafSerializer,
    ReferenceLeafCreateSerializer,
)

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_LEAF_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


class LeafListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/writing/leaves         → list own Storyline leaves
    POST /api/writing/leaves         → quick post (create leaf directly)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return LeafCreateSerializer
        return LeafSerializer

    def get_queryset(self):
        user = self.request.user
        drafts = self.request.query_params.get("drafts") == "true"
        qs = Leaf.objects.filter(
            author=user,
            deleted_at__isnull=True,
            published_at__isnull=drafts,
        ).select_related("author", "author__profile", "source_content_type", "image_file", "audio_file")

        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        return qs.order_by("-updated_at" if drafts else "-published_at")

    def create(self, request, *args, **kwargs):
        serializer = LeafCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Resolve image_file UUID to StoredFile instance
        image_file = None
        image_file_id = data.get("image_file")
        if image_file_id:
            image_file = get_object_or_404(StoredFile, pk=image_file_id)

        leaf = quick_post_leaf(
            author=request.user,
            body_text=data.get("body_text", ""),
            body_json=data.get("body_json"),
            kind=data.get("kind", "text"),
            link_url=data.get("link_url"),
            image_file=image_file,
            publish=data.get("publish", True),
        )

        return Response(
            LeafSerializer(leaf).data,
            status=status.HTTP_201_CREATED,
        )


class LeafDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PUT/DELETE /api/writing/leaves/<uuid:pk>
    """
    serializer_class = LeafSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrStaff]

    def get_queryset(self):
        return Leaf.objects.filter(deleted_at__isnull=True).select_related(
            "author", "author__profile", "source_content_type", "image_file", "audio_file",
        )


class LeafReferenceCreateView(APIView):
    """
    POST /api/writing/leaves/reference → create a reference leaf (curated card)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ReferenceLeafCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ct = resolve_content_type(data["source_content_type"])
        model_class = ct.model_class()
        source_obj = get_object_or_404(model_class, pk=data["source_object_id"])

        leaf = create_reference_leaf(
            author=request.user,
            source_object=source_obj,
            caption=data.get("caption", ""),
        )

        return Response(
            LeafSerializer(leaf).data,
            status=status.HTTP_201_CREATED,
        )


class SeedToLeafPromoteView(APIView):
    """
    POST /api/writing/seeds/<uuid:pk>/promote-to-leaf → Draftroom curation step
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        seed = get_object_or_404(Seed, pk=pk, author=request.user)
        try:
            leaf = promote_seed_to_leaf(seed=seed, author=request.user)
        except PromotionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            LeafSerializer(leaf).data,
            status=status.HTTP_201_CREATED,
        )


class LeafPromoteView(APIView):
    """
    POST /api/writing/leaves/<uuid:pk>/promote → promote Leaf to WritingPiece draft
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        leaf = get_object_or_404(Leaf, pk=pk, author=request.user)
        try:
            wc = promote_leaf_to_working_copy(leaf=leaf, author=request.user)
        except PromotionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {"id": str(wc.id), "title": getattr(wc, "title", "Untitled")},
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# Leaf Image Upload
# ============================================================================

class LeafImageUploadView(APIView):
    """
    POST /api/writing/leaves/upload-image
    Upload an image file for use in a Leaf. Returns StoredFile id + url.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [FormParser, MultiPartParser]

    def post(self, request):
        image = request.FILES.get("image")
        if not image:
            return Response(
                {"detail": "No image file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if image.size > MAX_LEAF_IMAGE_BYTES:
            return Response(
                {"detail": f"Image too large (max {MAX_LEAF_IMAGE_BYTES // (1024 * 1024)}MB)."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        content_type = (image.content_type or "").lower()
        if content_type not in ALLOWED_IMAGE_MIME:
            return Response(
                {"detail": f"Unsupported image type: {content_type or 'unknown'}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base = get_valid_filename(image.name or "")
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        unique = f"{uuid_mod.uuid4()}.{ext}" if ext else str(uuid_mod.uuid4())
        s3_key = f"leaves/images/{request.user.id}/{unique}"

        image.seek(0)
        saved_key = default_storage.save(s3_key, image)

        stored = StoredFile.objects.create(
            file_path=saved_key,
            file_name=image.name or "",
            file_type=image.content_type or "",
            file_size=image.size or 0,
            uploaded_by=request.user,
            source="web",
        )

        return Response(
            {"id": str(stored.pk), "url": stored.url},
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# Leaf Publish (draft → published)
# ============================================================================

class LeafPublishView(APIView):
    """
    POST /api/writing/leaves/<uuid:pk>/publish → publish a draft leaf
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        leaf = get_object_or_404(Leaf, pk=pk, author=request.user, deleted_at__isnull=True)
        if leaf.published_at:
            return Response(
                {"detail": "Leaf is already published."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        leaf.published_at = timezone.now()
        leaf.save(update_fields=["published_at", "updated_at"])
        return Response(LeafSerializer(leaf).data)


# ============================================================================
# Leaf Comments — REMOVED
# Comments are now placement-scoped. See placement_views.PlacementCommentListCreateView.
# Old endpoints:
#   GET/POST /api/writing/leaves/<leaf_id>/comments  → REMOVED
#   PUT/DELETE /api/writing/comments/<pk>            → see placement_views
# ============================================================================
