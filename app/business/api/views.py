# business/api/views.py

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models.group import Group
from groups.services.groups import GroupService

from business.models import Client, FixItem, FixItemStatus, Supplier, SupplyRequest, SupplyRequestStatus
from .serializers import FixItemSerializer, SupplierSerializer, SupplyRequestSerializer


def _get_group(slug):
    return get_object_or_404(Group, slug=slug)


def _require_member(request, group):
    membership = GroupService.get_user_membership(group, request.user)
    if not membership:
        return Response({"detail": "Not a member of this group."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _require_admin(request, group):
    membership = GroupService.get_user_membership(group, request.user)
    if not membership or not membership.is_admin():
        return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _group_ct(group):
    return ContentType.objects.get_for_model(group)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

class SupplierListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        qs = Supplier.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        return Response(SupplierSerializer(qs, many=True).data)

    def post(self, request, slug):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        serializer = SupplierSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        supplier = serializer.save(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            created_by=request.user,
        )
        return Response(SupplierSerializer(supplier).data, status=status.HTTP_201_CREATED)


class SupplierDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug, supplier_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        supplier = get_object_or_404(
            Supplier,
            pk=supplier_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        return Response(SupplierSerializer(supplier).data)

    def patch(self, request, slug, supplier_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        supplier = get_object_or_404(
            Supplier,
            pk=supplier_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        serializer = SupplierSerializer(supplier, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Supply Requests
# ---------------------------------------------------------------------------

class SupplyRequestListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        status_filter = request.query_params.get("status")
        qs = SupplyRequest.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        ).select_related("supplier")

        if status_filter and status_filter in SupplyRequestStatus.values:
            qs = qs.filter(status=status_filter)

        return Response(SupplyRequestSerializer(qs, many=True).data)


class SupplyRequestDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug, request_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        obj = get_object_or_404(
            SupplyRequest,
            pk=request_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        return Response(SupplyRequestSerializer(obj).data)

    def patch(self, request, slug, request_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        obj = get_object_or_404(
            SupplyRequest,
            pk=request_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        serializer = SupplyRequestSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Fix Items
# ---------------------------------------------------------------------------

class FixItemListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        status_filter = request.query_params.get("status")
        qs = FixItem.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )

        if status_filter and status_filter in FixItemStatus.values:
            qs = qs.filter(status=status_filter)
        else:
            # Default: exclude resolved
            qs = qs.exclude(status=FixItemStatus.RESOLVED)

        return Response(FixItemSerializer(qs, many=True).data)


class FixItemDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug, fix_item_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        obj = get_object_or_404(
            FixItem,
            pk=fix_item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        return Response(FixItemSerializer(obj).data)

    def patch(self, request, slug, fix_item_id):
        group = _get_group(slug)
        denied = _require_member(request, group)
        if denied:
            return denied

        ct = _group_ct(group)
        obj = get_object_or_404(
            FixItem,
            pk=fix_item_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        )
        serializer = FixItemSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Clients (operator-only)
# ---------------------------------------------------------------------------

class ClientListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({"detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

        clients = (
            Client.objects
            .select_related("group", "prospect")
            .filter(group__deleted_at__isnull=True)
            .order_by("-created_at")
        )

        data = [
            {
                "id": str(c.id),
                "group_slug": c.group.slug,
                "group_title": c.group.title,
                "primary_contact_name": c.primary_contact_name,
                "primary_contact_email": c.primary_contact_email,
                "primary_contact_phone": c.primary_contact_phone,
                "website": c.website,
                "business_type": c.business_type,
                "contract_notes": c.contract_notes,
                "billing_notes": c.billing_notes,
                "prospect_slug": c.prospect.slug if c.prospect_id else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in clients
        ]
        return Response(data)
