# groups/api/ownership_views.py
"""
API views for ownership change requests.
"""

from rest_framework import generics, permissions
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from groups.models import Group
from groups.models.ownership import (
    OwnershipChangeRequest,
    OwnershipRequestStatus,
)
from groups.services.ownership import (
    cancel_ownership_request,
    create_ownership_request,
    _assert_is_active_owner,
)


def _check_owner(request, group):
    """Return 403 Response if user is not an active owner, else None."""
    try:
        _assert_is_active_owner(group, request.user)
    except PermissionError:
        return Response(
            {"error": "Only active owners can manage ownership requests"},
            status=403,
        )
    return None


def _serialize_request(req):
    """Serialize an OwnershipChangeRequest to dict."""
    return {
        "id": str(req.id),
        "group_id": str(req.group_id),
        "action": req.action,
        "target_user_id": str(req.target_user_id),
        "requested_by_id": str(req.requested_by_id),
        "execute_after": req.execute_after.isoformat(),
        "status": req.status,
        "canceled_by_id": str(req.canceled_by_id) if req.canceled_by_id else None,
        "canceled_at": req.canceled_at.isoformat() if req.canceled_at else None,
        "executed_at": req.executed_at.isoformat() if req.executed_at else None,
        "failure_reason": req.failure_reason,
        "created_at": req.created_at.isoformat(),
    }


class OwnershipRequestCreateView(generics.GenericAPIView):
    """
    POST /api/groups/{slug}/ownership/requests/create

    Body: {"action": "ADD_OWNER", "target_user_id": "<uuid>"}

    Creates a time-delayed ownership change request.
    Only active owners can create requests.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        denied = _check_owner(request, group)
        if denied:
            return denied

        action = request.data.get("action")
        target_user_id = request.data.get("target_user_id")

        if not action or not target_user_id:
            return Response(
                {"error": "Both 'action' and 'target_user_id' are required"},
                status=400,
            )

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            target_user = User.objects.get(pk=target_user_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"error": "Target user not found"},
                status=404,
            )

        try:
            ownership_request = create_ownership_request(
                group=group,
                requested_by=request.user,
                action=action,
                target_user=target_user,
            )
        except PermissionError as e:
            return Response({"error": str(e)}, status=403)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response(_serialize_request(ownership_request), status=201)


class OwnershipRequestListView(generics.GenericAPIView):
    """
    GET /api/groups/{slug}/ownership/requests?status=PENDING

    Lists ownership change requests for the group.
    Only active owners can view.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        denied = _check_owner(request, group)
        if denied:
            return denied

        qs = OwnershipChangeRequest.objects.filter(group=group)

        status_filter = request.query_params.get("status")
        if status_filter:
            status_filter = status_filter.upper()
            valid = [c[0] for c in OwnershipRequestStatus.choices]
            if status_filter in valid:
                qs = qs.filter(status=status_filter)

        qs = qs.order_by("-created_at")

        return Response([_serialize_request(r) for r in qs])


class OwnershipRequestCancelView(generics.GenericAPIView):
    """
    POST /api/groups/{slug}/ownership/requests/{request_id}/cancel

    Cancels a pending ownership change request.
    Any active owner of the group can cancel.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, request_id):
        group = get_object_or_404(Group, slug=slug)

        denied = _check_owner(request, group)
        if denied:
            return denied

        try:
            ownership_request = OwnershipChangeRequest.objects.get(
                pk=request_id,
                group=group,
            )
        except OwnershipChangeRequest.DoesNotExist:
            return Response(
                {"error": "Ownership request not found"},
                status=404,
            )

        try:
            ownership_request = cancel_ownership_request(
                request=ownership_request,
                canceled_by=request.user,
            )
        except PermissionError as e:
            return Response({"error": str(e)}, status=403)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response(_serialize_request(ownership_request))
