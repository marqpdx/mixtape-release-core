# public_api/views_commons.py

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from commons.models import CommonsItem


class PublicCommonsListView(APIView):
    """
    GET /api/public/commons

    Returns published CommonsItems with geo data for map + listing.
    Supports ?type= and ?search= filters.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        qs = (
            CommonsItem.objects.filter(
                curation_status=CommonsItem.CurationStatus.PUBLISHED,
                deleted_at__isnull=True,
            )
            .select_related("recommended_by")
            .order_by("-published_at")
        )

        item_type = request.query_params.get("type")
        if item_type:
            qs = qs.filter(item_type=item_type)

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(title__icontains=search)
                | Q(summary__icontains=search)
                | Q(location_name__icontains=search)
            )

        items = []
        for item in qs:
            recommender = None
            if item.recommended_by:
                recommender = getattr(
                    item.recommended_by, "display_name", str(item.recommended_by)
                )
            items.append(
                {
                    "id": str(item.id),
                    "title": item.title,
                    "slug": item.slug,
                    "item_type": item.item_type,
                    "summary": item.summary,
                    "location_name": item.location_name,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "website": item.website,
                    "why_recommended": item.why_recommended,
                    "recommended_by_name": recommender,
                    "published_at": item.published_at,
                }
            )

        return Response(items)


class PublicCommonsDetailView(APIView):
    """
    GET /api/public/commons/{slug}

    Returns full detail for a single published CommonsItem.
    """

    permission_classes = [AllowAny]

    def get(self, request, slug):
        item = get_object_or_404(
            CommonsItem.objects.filter(
                curation_status=CommonsItem.CurationStatus.PUBLISHED,
                deleted_at__isnull=True,
            ).select_related("recommended_by"),
            slug=slug,
        )

        recommender = None
        if item.recommended_by:
            recommender = getattr(
                item.recommended_by, "display_name", str(item.recommended_by)
            )

        # Filaments (outgoing + incoming)
        filaments = []
        for f in item.filaments_out.select_related("target").all():
            filaments.append(
                {
                    "direction": "out",
                    "relation_type": f.relation_type,
                    "related_id": str(f.target.id),
                    "related_title": f.target.title,
                    "related_slug": f.target.slug,
                    "note": f.note,
                }
            )
        for f in item.filaments_in.select_related("source").all():
            filaments.append(
                {
                    "direction": "in",
                    "relation_type": f.relation_type,
                    "related_id": str(f.source.id),
                    "related_title": f.source.title,
                    "related_slug": f.source.slug,
                    "note": f.note,
                }
            )

        data = {
            "id": str(item.id),
            "title": item.title,
            "slug": item.slug,
            "item_type": item.item_type,
            "summary": item.summary,
            "body": item.body,
            "location_name": item.location_name,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "website": item.website,
            "contact_email": item.contact_email,
            "contact_links": item.contact_links,
            "instagram": item.instagram,
            "youtube": item.youtube,
            "rss": item.rss,
            "founder": item.founder,
            "why_recommended": item.why_recommended,
            "recommended_by_name": recommender,
            "published_at": item.published_at,
            "filaments": filaments,
        }

        return Response(data)
