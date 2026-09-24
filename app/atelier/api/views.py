import uuid

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from classifications.models import Category, ClassificationUsage, Tag
from writing.models import WritingPiece, WritingSeries, WritingSynopsis

from relations.models import RelationshipType
from relations.service import RelationshipService

from ..models import WritingMarkerOccurrence
from ..services import compute_craft_readiness, detect_and_sync_markers
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


def _synopsis_response(synopsis, piece=None) -> dict:
    result = {
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
    if piece is not None:
        result["excerpt"] = piece.excerpt or ""
    return result


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
        return Response(_synopsis_response(synopsis, piece=piece))

    def patch(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        synopsis = self._get_or_create_synopsis(piece)

        update_fields = []
        for summary_type, (text_field, confirmed_field) in _SUMMARY_FIELD_MAP.items():
            if summary_type in request.data:
                setattr(synopsis, text_field, request.data[summary_type])
                setattr(synopsis, confirmed_field, False)
                update_fields.append(text_field)
                update_fields.append(confirmed_field)

        if not update_fields:
            return Response({"detail": "No valid summary fields provided."}, status=400)

        update_fields.append("updated_at")
        synopsis.save(update_fields=update_fields)
        return Response(_synopsis_response(synopsis))


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def _serialize_series(series) -> dict:
    return {"id": str(series.id), "title": series.title, "slug": series.slug}


def _available_series(piece):
    """Series scoped to the piece's group sponsor, or group-less series for user-sponsored pieces."""
    if piece.sponsor_content_type and piece.sponsor_content_type.model == "group":
        return WritingSeries.objects.filter(group_id=piece.sponsor_object_id)
    return WritingSeries.objects.filter(group__isnull=True)


class SeriesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        current = _serialize_series(piece.series) if piece.series_id else None
        available = [_serialize_series(s) for s in _available_series(piece)]
        return Response({"current": current, "available": available})

    def put(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        series_id = request.data.get("series_id")
        if not series_id:
            return Response({"detail": "series_id required."}, status=400)
        series = get_object_or_404(_available_series(piece), id=series_id)
        piece.series = series
        piece.save(update_fields=["series", "updated_at"])
        return Response({"current": _serialize_series(series)})

    def delete(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        piece.series = None
        piece.save(update_fields=["series", "updated_at"])
        return Response(status=204)


class SeriesSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        q = request.query_params.get("q", "").strip()
        qs = _available_series(piece)
        if q:
            qs = qs.filter(title__icontains=q)
        return Response([_serialize_series(s) for s in qs[:20]])


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


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

def _valid_editorial_verbs():
    return list(
        RelationshipType.objects.filter(domain="editorial").values_list("slug", flat=True)
    )


def _serialize_relation_piece(piece):
    return {
        "id": str(piece.id),
        "title": piece.title or "Untitled",
        "slug": piece.slug,
    }


def _serialize_outgoing(r):
    target = r.target
    return {
        "id": str(r.id),
        "verb": r.relationship_type.slug,
        "verb_label": r.relationship_type.label,
        "status": r.lifecycle,
        "note": r.notes,
        "target": _serialize_relation_piece(target) if target else None,
    }


def _serialize_incoming(r):
    source = r.source
    created_by = r.created_by
    return {
        "id": str(r.id),
        "verb": r.relationship_type.slug,
        "verb_label": r.relationship_type.label,
        "status": r.lifecycle,
        "note": r.notes,
        "source": _serialize_relation_piece(source) if source else None,
        "created_by": {
            "id": str(created_by.id),
            "display_name": created_by.get_full_name() or created_by.username,
        } if created_by else None,
    }


class RelationListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        outgoing = RelationshipService.get_outgoing(piece, domain="editorial")
        incoming = RelationshipService.get_incoming(piece, domain="editorial")
        return Response({
            "outgoing": [_serialize_outgoing(r) for r in outgoing],
            "incoming": [_serialize_incoming(r) for r in incoming],
        })

    def post(self, request, piece_slug):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err

        target_slug = request.data.get("target_slug")
        verb = request.data.get("verb")
        note = request.data.get("note", "")

        if not target_slug:
            return Response({"detail": "target_slug required."}, status=400)

        valid_verbs = _valid_editorial_verbs()
        if verb not in valid_verbs:
            return Response({"detail": f"Invalid verb. Choose from: {sorted(valid_verbs)}"}, status=400)

        target = get_object_or_404(WritingPiece, slug=target_slug)
        if target.pk == piece.pk:
            return Response({"detail": "A piece cannot relate to itself."}, status=400)

        existing = RelationshipService.get_outgoing(piece, type_slug=verb).filter(
            target_object_id=target.pk
        ).first()
        if existing:
            return Response(_serialize_outgoing(existing), status=200)

        relation = RelationshipService.create_relationship(
            type_slug=verb,
            source=piece,
            target=target,
            created_by=request.user,
            notes=note,
        )
        return Response(_serialize_outgoing(relation), status=201)


class RelationDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, piece_slug, relation_id):
        from relations.models import Relationship
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        ct = ContentType.objects.get_for_model(WritingPiece)
        relation = get_object_or_404(
            Relationship,
            id=relation_id,
            source_content_type=ct,
            source_object_id=piece.pk,
            created_by=request.user,
        )
        RelationshipService.archive_relationship(relationship_id=relation.id, archived_by=request.user)
        return Response(status=204)


class RelationAcknowledgeView(APIView):
    """Target piece author acknowledges an incoming relation."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_slug, relation_id):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        ct = ContentType.objects.get_for_model(WritingPiece)
        from relations.models import Relationship
        relation = get_object_or_404(
            Relationship,
            id=relation_id,
            target_content_type=ct,
            target_object_id=piece.pk,
        )
        if relation.lifecycle in ("acknowledged", "mutual"):
            return Response(_serialize_incoming(relation))
        RelationshipService.acknowledge_relationship(
            relationship_id=relation.id, acknowledged_by=request.user
        )
        relation.refresh_from_db()
        return Response(_serialize_incoming(relation))


class RelationDismissView(APIView):
    """Target piece author dismisses an incoming relation (archives it from their view)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_slug, relation_id):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        ct = ContentType.objects.get_for_model(WritingPiece)
        from relations.models import Relationship
        relation = get_object_or_404(
            Relationship,
            id=relation_id,
            target_content_type=ct,
            target_object_id=piece.pk,
        )
        RelationshipService.archive_relationship(relationship_id=relation.id, archived_by=request.user)
        return Response(status=204)


class PieceSearchView(APIView):
    """Search WritingPiece by title for relation target selection."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < 2:
            return Response([])
        pieces = (
            WritingPiece.objects
            .filter(title__icontains=q)
            .exclude(title__isnull=True)
            .exclude(title="")
            .order_by("-updated_at")[:20]
        )
        return Response([_serialize_relation_piece(p) for p in pieces])


# ---------------------------------------------------------------------------
# Markers (CR-002 — Ad Hoc Semantic Markers)
# ---------------------------------------------------------------------------

def _serialize_marker(occ: WritingMarkerOccurrence) -> dict:
    return {
        "id": str(occ.id),
        "raw_name": occ.raw_name,
        "raw_marker": occ.raw_marker,
        "char_offset": occ.char_offset,
        "status": occ.status,
        "label": occ.label,
        "body": occ.body,
        "created_at": occ.created_at.isoformat(),
    }


class MarkerListView(APIView):
    """
    GET — returns markers for a piece.
    ?status=affirmed  → affirmed markers only, no sync (reader-safe)
    default           → sync then return pending (writer Atelier use)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        status_filter = request.query_params.get("status")
        if status_filter == WritingMarkerOccurrence.STATUS_AFFIRMED:
            piece = get_object_or_404(WritingPiece, slug=piece_slug)
            occurrences = WritingMarkerOccurrence.objects.filter(
                piece=piece, status=WritingMarkerOccurrence.STATUS_AFFIRMED
            ).order_by("char_offset")
            return Response([_serialize_marker(occ) for occ in occurrences])

        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err
        pending = detect_and_sync_markers(piece)
        return Response([_serialize_marker(occ) for occ in pending])


class MarkerIndexView(APIView):
    """
    GET /api/atelier/markers/?raw_name=q
    Cross-piece index: all affirmed markers of a given type for the current user.
    Returns occurrences with piece slug and title for navigation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        raw_name = request.query_params.get("raw_name", "").strip()
        if not raw_name:
            return Response({"detail": "raw_name is required."}, status=400)

        user = request.user
        user_ct = ContentType.objects.get_for_model(user.__class__)

        occurrences = (
            WritingMarkerOccurrence.objects
            .filter(
                raw_name=raw_name,
                status=WritingMarkerOccurrence.STATUS_AFFIRMED,
                sponsor_content_type=user_ct,
                sponsor_object_id=user.pk,
            )
            .select_related("piece")
            .order_by("piece__title", "char_offset")
        )

        result = []
        for occ in occurrences:
            result.append({
                "id": str(occ.id),
                "raw_name": occ.raw_name,
                "label": occ.label,
                "body": occ.body,
                "char_offset": occ.char_offset,
                "piece": {
                    "id": str(occ.piece.pk),
                    "slug": occ.piece.slug,
                    "title": occ.piece.title or "Untitled",
                },
            })
        return Response(result)


class MarkerDetailView(APIView):
    """PATCH — affirm or dismiss a marker occurrence."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, piece_slug, marker_id):
        piece, err = _get_piece_for_author(piece_slug, request.user)
        if err:
            return err

        occ = get_object_or_404(WritingMarkerOccurrence, id=marker_id, piece=piece)
        action = request.data.get("action")

        if action == "affirm":
            label = request.data.get("label", occ.label)
            body = request.data.get("body", occ.body)
            if not label:
                return Response({"detail": "label is required to affirm a marker."}, status=400)
            occ.label = label
            occ.body = body
            occ.status = WritingMarkerOccurrence.STATUS_AFFIRMED
            occ.affirmed_at = timezone.now()
            occ.save(update_fields=["label", "body", "status", "affirmed_at", "updated_at"])
        elif action == "dismiss":
            occ.status = WritingMarkerOccurrence.STATUS_DISMISSED
            occ.dismissed_at = timezone.now()
            occ.save(update_fields=["status", "dismissed_at", "updated_at"])
        else:
            return Response({"detail": "action must be 'affirm' or 'dismiss'."}, status=400)

        return Response(_serialize_marker(occ))
