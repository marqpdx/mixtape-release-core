from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from classifications.models import Category, ClassificationUsage, Tag
from writing.models import WritingPiece

from ..services import compute_craft_readiness
from .serializers import CategorySerializer, TagSerializer


def _get_piece_for_author(slug, user):
    piece = get_object_or_404(WritingPiece, slug=slug)
    if piece.author_id != user.id:
        return None, Response({"detail": "Not found."}, status=404)
    return piece, None


class ReadinessView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        return Response(compute_craft_readiness(piece))


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TagListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        tag_ct = ContentType.objects.get_for_model(Tag)
        usages = piece.tags.filter(classification_content_type=tag_ct)
        return Response([TagSerializer.from_usage(u) for u in usages])

    def post(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        tag_slug = request.data.get("tag_slug")
        tag_id = request.data.get("tag_id")
        if tag_slug:
            tag = get_object_or_404(Tag, slug=tag_slug)
        elif tag_id:
            tag = get_object_or_404(Tag, id=tag_id)
        else:
            return Response({"detail": "tag_slug or tag_id required."}, status=400)
        usage = piece.add_classification(tag)
        return Response(TagSerializer.from_usage(usage), status=201)


class TagDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, piece_slug, cu_id):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        piece_ct = ContentType.objects.get_for_model(WritingPiece)
        usage = get_object_or_404(
            ClassificationUsage,
            id=cu_id,
            classification_client_content_type=piece_ct,
            classification_client_object_id=str(piece.pk),
        )
        piece.remove_classification(usage.classification)
        return Response(status=204)


class TagSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])
        tags = Tag.objects.filter(title__icontains=q)[:20]
        return Response([TagSerializer.from_tag(t) for t in tags])


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class CategoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _current_usage(self, piece):
        cat_ct = ContentType.objects.get_for_model(Category)
        return piece.categories.filter(classification_content_type=cat_ct).first()

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        usage = self._current_usage(piece)
        return Response(CategorySerializer.from_usage(usage) if usage else None)

    def put(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        category_slug = request.data.get("category_slug")
        category_id = request.data.get("category_id")
        if category_slug:
            category = get_object_or_404(Category, slug=category_slug)
        elif category_id:
            category = get_object_or_404(Category, id=category_id)
        else:
            return Response({"detail": "category_slug or category_id required."}, status=400)
        # Replace existing category
        cat_ct = ContentType.objects.get_for_model(Category)
        for existing in piece.categories.filter(classification_content_type=cat_ct):
            piece.remove_classification(existing.classification)
        usage = piece.add_classification(category)
        return Response(CategorySerializer.from_usage(usage))

    def delete(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        cat_ct = ContentType.objects.get_for_model(Category)
        for existing in piece.categories.filter(classification_content_type=cat_ct):
            piece.remove_classification(existing.classification)
        return Response(status=204)
