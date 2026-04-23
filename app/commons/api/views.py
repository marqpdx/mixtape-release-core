# commons/api/views.py

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from commons.models import CommonsItem
from commons import services as commons_service

from .serializers import (
    CommonsItemListSerializer,
    CommonsItemDetailSerializer,
    CommonsItemCreateSerializer,
    CommonsItemCurationSerializer,
    FilamentCreateSerializer,
    _serialize_commons_relationship,
)


def _require_superuser(request):
    """Return error Response if user is not superuser, else None."""
    if not request.user.is_superuser:
        return Response(
            {"detail": "Superuser access required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class CommonsItemListCreateView(generics.GenericAPIView):
    """
    GET  — List CommonsItems (filterable by curation_status, item_type)
    POST — Capture a new CommonsItem
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CommonsItemCreateSerializer
        return CommonsItemListSerializer

    def get_queryset(self):
        qs = CommonsItem.objects.filter(deleted_at__isnull=True)

        curation_status = self.request.query_params.get("status")
        if curation_status:
            qs = qs.filter(curation_status=curation_status)

        item_type = self.request.query_params.get("type")
        if item_type:
            qs = qs.filter(item_type=item_type)

        return qs.order_by("-created_at")

    def get(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        qs = self.get_queryset()
        serializer = CommonsItemListSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        denied = _require_superuser(request)
        if denied:
            return denied

        serializer = CommonsItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item = commons_service.capture_item(
            user=request.user,
            source_url=data.get("source_url", ""),
            title=data.get("title", ""),
            why_recommended=data.get("why_recommended", ""),
        )

        # Apply optional fields
        if data.get("item_type"):
            item.item_type = data["item_type"]
        if data.get("location_name"):
            item.location_name = data["location_name"]
        if data.get("item_type") or data.get("location_name"):
            item.save()

        detail = CommonsItemDetailSerializer(item)
        return Response(detail.data, status=status.HTTP_201_CREATED)


class CommonsItemDetailView(generics.GenericAPIView):
    """
    GET   — Retrieve a CommonsItem
    PATCH — Update (curation edits)
    DELETE — Soft delete
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, pk):
        return get_object_or_404(CommonsItem, pk=pk, deleted_at__isnull=True)

    def get(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        item = self._get_item(pk)
        serializer = CommonsItemDetailSerializer(item)
        return Response(serializer.data)

    def patch(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        item = self._get_item(pk)
        serializer = CommonsItemCurationSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        detail = CommonsItemDetailSerializer(item)
        return Response(detail.data)

    def delete(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        item = self._get_item(pk)
        from django.utils import timezone
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommonsItemAdvanceView(generics.GenericAPIView):
    """
    POST — Advance curation status.
    Body: {"target_status": "in_curation"}
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        item = get_object_or_404(CommonsItem, pk=pk, deleted_at__isnull=True)
        target_status = request.data.get("target_status")

        if not target_status:
            return Response(
                {"detail": "target_status is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            item = commons_service.advance_status(item, request.user, target_status)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CommonsItemDetailSerializer(item)
        return Response(serializer.data)


class CommonsItemRejectView(generics.GenericAPIView):
    """POST — Reject a CommonsItem."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        item = get_object_or_404(CommonsItem, pk=pk, deleted_at__isnull=True)

        try:
            item = commons_service.reject_item(item, request.user)
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CommonsItemDetailSerializer(item)
        return Response(serializer.data)


class FilamentListCreateView(generics.GenericAPIView):
    """
    GET  — List commons-domain Relationships for a CommonsItem (both directions)
    POST — Create a new commons-domain Relationship from this item
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        from relations.service import RelationshipService
        item = get_object_or_404(CommonsItem, pk=pk, deleted_at__isnull=True)
        outgoing = [_serialize_commons_relationship(r) for r in RelationshipService.get_outgoing(item, domain="commons")]
        incoming = [_serialize_commons_relationship(r) for r in RelationshipService.get_incoming(item, domain="commons")]
        return Response({"outgoing": outgoing, "incoming": incoming})

    def post(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        from relations.service import RelationshipService
        source = get_object_or_404(CommonsItem, pk=pk, deleted_at__isnull=True)
        serializer = FilamentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target = get_object_or_404(
            CommonsItem, pk=data["target_id"], deleted_at__isnull=True
        )

        relationship = commons_service.create_filament(
            source=source,
            target=target,
            relation_type=data["relation_type"],
            note=data.get("note", ""),
            created_by=request.user,
        )

        return Response(
            _serialize_commons_relationship(relationship),
            status=status.HTTP_201_CREATED,
        )


class FilamentDeleteView(generics.GenericAPIView):
    """DELETE — Archive a commons-domain Relationship."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        denied = _require_superuser(request)
        if denied:
            return denied

        from relations.models import Relationship
        from relations.service import RelationshipService
        relationship = get_object_or_404(Relationship, pk=pk)
        RelationshipService.archive_relationship(relationship_id=relationship.id, archived_by=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
