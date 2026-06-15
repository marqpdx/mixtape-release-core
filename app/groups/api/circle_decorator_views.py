# groups/api/circle_decorator_views.py

"""
API endpoints for Circle decorator apply/remove and deliverable intent CRUD.

CR-E endpoints:
  POST   /api/groups/<slug>/apply-decorator/         — apply decorator or profile
  DELETE /api/groups/<slug>/decorators/<code>/        — remove decorator
  GET    /api/groups/<slug>/deliverable-intent/       — fetch CDI
  PATCH  /api/groups/<slug>/deliverable-intent/       — update CDI fields
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from groups.models.circle import DeliverableType, DeliverableStatus
from groups.services.circles import (
    CircleDecoratorError,
    apply_deliverable_intent,
    apply_working_circle_profile,
    remove_deliverable_intent,
    update_deliverable_intent,
)
from groups.services.groups import GroupService


def _require_admin(group, user, response_class=Response):
    if not GroupService.is_user_admin(group, user):
        return Response({"detail": "Admin required."}, status=status.HTTP_403_FORBIDDEN)
    return None


class CircleApplyDecoratorView(APIView):
    """
    POST /api/groups/<slug>/apply-decorator/

    Apply a single decorator or a profile bundle to a Circle.

    Body (decorator):
      { "decorator_code": "hasDeliverableIntent", "deliverable_type": "puddlejump_doc" }

    Body (profile):
      { "profile_code": "profile__WorkingCircle", "deliverable_type": "puddlejump_doc" }

    Permission: circle admin only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_admin(group, request.user)
        if denied:
            return denied

        if group.group_type != "circle":
            return Response(
                {"detail": "Decorators may only be applied to circles via this endpoint."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile_code = request.data.get("profile_code")
        decorator_code = request.data.get("decorator_code")
        deliverable_type = request.data.get("deliverable_type")

        valid_types = [c[0] for c in DeliverableType.choices]

        try:
            if profile_code == "profile__WorkingCircle":
                if deliverable_type not in valid_types:
                    return Response(
                        {"detail": f"deliverable_type must be one of: {valid_types}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                result = apply_working_circle_profile(
                    group, deliverable_type=deliverable_type, assigned_by=request.user
                )
                cdi = result["deliverable_intent"]
                return Response(
                    {
                        "applied": "profile__WorkingCircle",
                        "deliverable_intent": {
                            "deliverable_type": cdi.deliverable_type,
                            "deliverable_status": cdi.deliverable_status,
                        } if cdi else None,
                    },
                    status=status.HTTP_201_CREATED,
                )

            elif decorator_code == "hasDeliverableIntent":
                if deliverable_type not in valid_types:
                    return Response(
                        {"detail": f"deliverable_type must be one of: {valid_types}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                result = apply_deliverable_intent(
                    group, deliverable_type=deliverable_type, assigned_by=request.user
                )
                cdi = result["deliverable_intent"]
                return Response(
                    {
                        "applied": "hasDeliverableIntent",
                        "deliverable_intent": {
                            "deliverable_type": cdi.deliverable_type,
                            "deliverable_status": cdi.deliverable_status,
                        },
                    },
                    status=status.HTTP_201_CREATED,
                )

            else:
                return Response(
                    {"detail": "Unsupported decorator_code or profile_code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except CircleDecoratorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CircleRemoveDecoratorView(APIView):
    """
    DELETE /api/groups/<slug>/decorators/<str:decorator_code>/

    Remove a decorator from a Circle.

    For hasDeliverableIntent: also deletes the CircleDeliverableIntent record.
    Permission: circle admin only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, slug, decorator_code):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_admin(group, request.user)
        if denied:
            return denied

        if group.group_type != "circle":
            return Response(
                {"detail": "Only circles support this endpoint."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if decorator_code == "hasDeliverableIntent":
                remove_deliverable_intent(group)
                return Response(status=status.HTTP_204_NO_CONTENT)
            else:
                return Response(
                    {"detail": f"Removal of '{decorator_code}' not supported via this endpoint."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except CircleDecoratorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class CircleDeliverableIntentView(APIView):
    """
    GET   /api/groups/<slug>/deliverable-intent/  — fetch CDI (member+)
    PATCH /api/groups/<slug>/deliverable-intent/  — update CDI fields (admin)
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_circle(self, slug):
        return get_object_or_404(Group, slug=slug, is_active=True, group_type="circle")

    def get(self, request, slug):
        group = self._get_circle(slug)
        if not GroupService.get_user_membership(group, request.user):
            return Response({"detail": "Members only."}, status=status.HTTP_403_FORBIDDEN)

        try:
            cdi = group.deliverable_intent
        except Exception:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response({
            "deliverable_type": cdi.deliverable_type,
            "deliverable_status": cdi.deliverable_status,
        })

    def patch(self, request, slug):
        group = self._get_circle(slug)
        denied = _require_admin(group, request.user)
        if denied:
            return denied

        valid_types = [c[0] for c in DeliverableType.choices]
        valid_statuses = [c[0] for c in DeliverableStatus.choices]

        deliverable_type = request.data.get("deliverable_type")
        deliverable_status = request.data.get("deliverable_status")

        if deliverable_type is not None and deliverable_type not in valid_types:
            return Response(
                {"detail": f"deliverable_type must be one of: {valid_types}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if deliverable_status is not None and deliverable_status not in valid_statuses:
            return Response(
                {"detail": f"deliverable_status must be one of: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cdi = update_deliverable_intent(
                group,
                deliverable_type=deliverable_type,
                deliverable_status=deliverable_status,
            )
        except CircleDecoratorError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "deliverable_type": cdi.deliverable_type,
            "deliverable_status": cdi.deliverable_status,
        })
