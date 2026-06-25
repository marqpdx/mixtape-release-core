# public_api/views_commons.py

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from commons.models import Leaf


def _leaf_list_item(leaf):
    author_name = getattr(leaf.author, "display_name", None) or str(leaf.author)
    return {
        "id": str(leaf.id),
        "kind": leaf.kind,
        "caption": leaf.caption,
        "body_text": leaf.body_text,
        "link_url": leaf.link_url,
        "link_preview": leaf.link_preview,
        "author_display_name": author_name,
        "place_id": str(leaf.place_id) if leaf.place_id else None,
        "occurred_at": leaf.occurred_at,
        "published_at": leaf.published_at,
    }


class PublicCommonsListView(APIView):
    """
    GET /api/public/commons

    Returns closed, Commons-shared, public Leaf records.
    Supports ?kind= and ?search= filters.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        qs = (
            Leaf.objects.filter(
                state=Leaf.STATE_CLOSED,
                library_only=False,
                visibility="public",
            )
            .select_related("author")
            .order_by("-published_at")
        )

        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(caption__icontains=search) | Q(body_text__icontains=search)
            )

        return Response([_leaf_list_item(leaf) for leaf in qs])


class PublicCommonsDetailView(APIView):
    """
    GET /api/public/commons/{id}

    Returns full detail for a single Commons-shared Leaf, including entries.
    """

    permission_classes = [AllowAny]

    def get(self, request, pk):
        leaf = get_object_or_404(
            Leaf.objects.filter(
                state=Leaf.STATE_CLOSED,
                library_only=False,
                visibility="public",
            ).select_related("author", "place").prefetch_related("entries"),
            pk=pk,
        )

        author_name = getattr(leaf.author, "display_name", None) or str(leaf.author)

        entries = [
            {
                "id": str(e.id),
                "kind": e.kind,
                "position": e.position,
                "body_text": e.body_text,
                "body_json": e.body_json,
                "shared": e.shared,
            }
            for e in leaf.entries.filter(shared=True)
        ]

        data = {
            "id": str(leaf.id),
            "kind": leaf.kind,
            "caption": leaf.caption,
            "body_text": leaf.body_text,
            "body_json": leaf.body_json,
            "link_url": leaf.link_url,
            "link_preview": leaf.link_preview,
            "author_display_name": author_name,
            "place_id": str(leaf.place_id) if leaf.place_id else None,
            "occurred_at": leaf.occurred_at,
            "published_at": leaf.published_at,
            "entries": entries,
        }

        return Response(data)
