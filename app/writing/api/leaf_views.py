# writing/api/leaf_views.py

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.shared.contenttypes import resolve_content_type
from writing.api.permissions import IsAuthorOrStaff
from writing.models import Leaf, LeafComment, Seed
from writing.services import (
    create_reference_leaf,
    promote_leaf_to_working_copy,
    promote_seed_to_leaf,
    quick_post_leaf,
    PromotionError,
)

from .serializers import (
    LeafCommentSerializer,
    LeafCreateSerializer,
    LeafSerializer,
    ReferenceLeafCreateSerializer,
)


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
        qs = Leaf.objects.filter(
            author=user,
            deleted_at__isnull=True,
            published_at__isnull=False,
        ).select_related("author", "author__profile", "source_content_type")

        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        return qs.order_by("-published_at")

    def create(self, request, *args, **kwargs):
        serializer = LeafCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        leaf = quick_post_leaf(
            author=request.user,
            body_text=data.get("body_text", ""),
            body_json=data.get("body_json"),
            kind=data.get("kind", "text"),
            link_url=data.get("link_url"),
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
        return Leaf.objects.filter(deleted_at__isnull=True)


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
# Leaf Comments
# ============================================================================

class LeafCommentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/writing/leaves/<uuid:leaf_id>/comments
    POST /api/writing/leaves/<uuid:leaf_id>/comments
    """
    serializer_class = LeafCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        leaf_id = self.kwargs["leaf_id"]
        return LeafComment.objects.filter(
            leaf_id=leaf_id,
            parent__isnull=True,
            is_approved=True,
            deleted_at__isnull=True,
        ).select_related(
            "author", "author__profile",
        ).prefetch_related(
            "replies__author", "replies__author__profile",
        )

    def perform_create(self, serializer):
        leaf_id = self.kwargs["leaf_id"]
        leaf = get_object_or_404(Leaf, pk=leaf_id)
        serializer.save(author=self.request.user, leaf=leaf)


class LeafCommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    PUT/DELETE /api/writing/comments/<uuid:pk>
    """
    serializer_class = LeafCommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrStaff]

    def get_queryset(self):
        return LeafComment.objects.filter(deleted_at__isnull=True)
