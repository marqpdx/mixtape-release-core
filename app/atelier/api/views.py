from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from classifications.models import Category, ClassificationUsage, Tag
from writing.models import WritingPiece, WritingSynopsis

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


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

_SUMMARY_FIELD_MAP = {
    "public_synopsis": ("description", "public_synopsis_confirmed"),
    "linkedin_synopsis": ("linkedin_copy", "linkedin_synopsis_confirmed"),
    "internal_abstract": ("internal_abstract", "internal_abstract_confirmed"),
}

_VALID_TYPES = set(_SUMMARY_FIELD_MAP.keys())


def _synopsis_response(synopsis) -> dict:
    return {
        "public_synopsis": {
            "text": synopsis.description,
            "confirmed": synopsis.public_synopsis_confirmed,
        },
        "linkedin_synopsis": {
            "text": synopsis.linkedin_copy,
            "confirmed": synopsis.linkedin_synopsis_confirmed,
        },
        "internal_abstract": {
            "text": synopsis.internal_abstract,
            "confirmed": synopsis.internal_abstract_confirmed,
        },
    }


class SummariesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_or_create_synopsis(self, piece):
        synopsis, _ = WritingSynopsis.objects.get_or_create(piece=piece)
        return synopsis

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        synopsis = self._get_or_create_synopsis(piece)
        return Response(_synopsis_response(synopsis))

    def patch(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        synopsis = self._get_or_create_synopsis(piece)

        update_fields = []
        for summary_type, (text_field, _) in _SUMMARY_FIELD_MAP.items():
            if summary_type in request.data:
                setattr(synopsis, text_field, request.data[summary_type])
                update_fields.append(text_field)

        if not update_fields:
            return Response({"detail": "No valid summary fields provided."}, status=400)

        update_fields.append("updated_at")
        synopsis.save(update_fields=update_fields)
        return Response(_synopsis_response(synopsis))


class SummariesConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err

        types = request.data.get("types", [])
        invalid = set(types) - _VALID_TYPES
        if invalid:
            return Response({"detail": f"Unknown summary types: {sorted(invalid)}"}, status=400)
        if not types:
            return Response({"detail": "types list required."}, status=400)

        synopsis, _ = WritingSynopsis.objects.get_or_create(piece=piece)
        update_fields = []
        for summary_type in types:
            _, confirmed_field = _SUMMARY_FIELD_MAP[summary_type]
            setattr(synopsis, confirmed_field, True)
            update_fields.append(confirmed_field)

        update_fields.append("updated_at")
        synopsis.save(update_fields=update_fields)
        return Response(_synopsis_response(synopsis))
