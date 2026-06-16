# drop/api/views.py
from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, IntegerField, Value, When
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drop.models import Drop, DropWeight
from groups.api.views import GroupService
from groups.models import Group
from inkwell.stackroom_enqueue import enqueue_stackroom_ingest

from .serializers import DropCreateSerializer, DropSerializer


def _get_group_or_404(slug):
    try:
        return Group.objects.get(slug=slug)
    except Group.DoesNotExist:
        return None


_WEIGHT_ORDER = {
    DropWeight.PINNED: 0,
    DropWeight.STANDARD: 1,
    DropWeight.SOCIAL: 2,
}


class GroupDropsListCreateView(APIView):
    """
    GET  /api/groups/<slug>/drops/  — list active drops (pinned → standard → social)
    POST /api/groups/<slug>/drops/  — create a drop
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        group = _get_group_or_404(slug)
        if not group:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_active:
            return Response({"detail": "Membership required."}, status=status.HTTP_403_FORBIDDEN)

        ct = ContentType.objects.get_for_model(Group)
        drops = (
            Drop.objects.filter(
                content_type=ct,
                object_id=group.id,
                is_archived=False,
            )
            .annotate(
                weight_order=Case(
                    When(weight=DropWeight.PINNED, then=Value(0)),
                    When(weight=DropWeight.STANDARD, then=Value(1)),
                    When(weight=DropWeight.SOCIAL, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
            .order_by("weight_order", "-created_at")
            .select_related("created_by")
        )

        return Response(DropSerializer(drops, many=True).data)

    def post(self, request, slug):
        group = _get_group_or_404(slug)
        if not group:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_active:
            return Response({"detail": "Membership required."}, status=status.HTTP_403_FORBIDDEN)

        serializer = DropCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        weight = data.get("weight", DropWeight.STANDARD)

        # Members may only create social drops; steward/admin can create any weight.
        is_steward_or_admin = membership.is_admin() or membership.is_steward()
        if weight != DropWeight.SOCIAL and not is_steward_or_admin:
            return Response(
                {"detail": "Only stewards and admins can create info or pinned drops."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Enforce unique handle within the group — on collision, reject and hint.
        ct = ContentType.objects.get_for_model(Group)
        if Drop.objects.filter(content_type=ct, object_id=group.id, handle=data["handle"], is_archived=False).exists():
            return Response(
                {"detail": f"A drop with handle @{data['handle']} already exists in this group."},
                status=status.HTTP_409_CONFLICT,
            )

        drop = Drop.objects.create(
            handle=data["handle"],
            content=data["content"],
            weight=weight,
            content_type=ct,
            object_id=group.id,
            created_by=request.user,
            event_date=data.get("event_date"),
            related_handle=data.get("related_handle") or "",
            almanac_event_id=data.get("almanac_event_id"),
            expires_at=data.get("expires_at"),
        )

        enqueue_stackroom_ingest(drop, reason="drop_created")

        return Response(DropSerializer(drop).data, status=status.HTTP_201_CREATED)


class GroupDropArchiveView(APIView):
    """
    POST /api/groups/<slug>/drops/<drop_id>/archive/  — archive a drop

    Members may archive their own social drops.
    Stewards/admins may archive any drop.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug, drop_id):
        group = _get_group_or_404(slug)
        if not group:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_active:
            return Response({"detail": "Membership required."}, status=status.HTTP_403_FORBIDDEN)

        ct = ContentType.objects.get_for_model(Group)
        try:
            drop = Drop.objects.get(pk=drop_id, content_type=ct, object_id=group.id)
        except Drop.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        is_steward_or_admin = membership.is_admin() or membership.is_steward()
        is_own_social = drop.weight == DropWeight.SOCIAL and drop.created_by_id == request.user.id

        if not is_steward_or_admin and not is_own_social:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        drop.is_archived = True
        drop.save(update_fields=["is_archived"])

        return Response({"archived": True})
