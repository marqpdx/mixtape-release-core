# appearance/api/views.py

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from appearance.models import GroupThemeSettings
from groups.models import Group, GroupMembership

from .serializers import (
    GroupThemeSettingsSerializer,
    GroupThemeSettingsUpdateSerializer,
)


class GroupThemeSettingsView(APIView):
    """
    GET /api/appearance/groups/{slug}/themes
    PATCH /api/appearance/groups/{slug}/themes
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_group_membership(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True,
        ).first()
        return group, membership

    def _has_access(self, membership):
        return membership and (membership.is_admin() or membership.is_steward())

    def get(self, request, slug):
        group, membership = self._get_group_membership(request, slug)
        if not membership:
            return Response(
                {"error": "You must be a member to view group themes"},
                status=status.HTTP_403_FORBIDDEN,
            )

        settings, _ = GroupThemeSettings.objects.get_or_create(group=group)
        serializer = GroupThemeSettingsSerializer(settings)
        return Response(serializer.data)

    def patch(self, request, slug):
        group, membership = self._get_group_membership(request, slug)
        if not self._has_access(membership):
            return Response(
                {"error": "Only admins and stewards can manage group themes"},
                status=status.HTTP_403_FORBIDDEN,
            )

        settings, _ = GroupThemeSettings.objects.get_or_create(group=group)

        serializer = GroupThemeSettingsUpdateSerializer(
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        update_fields = []
        if "hidden_theme_ids" in serializer.validated_data:
            settings.hidden_theme_ids = serializer.validated_data["hidden_theme_ids"]
            update_fields.append("hidden_theme_ids")
        if "group_themes" in serializer.validated_data:
            settings.group_themes = serializer.validated_data["group_themes"]
            update_fields.append("group_themes")

        if update_fields:
            settings.save(update_fields=update_fields)

        response = GroupThemeSettingsSerializer(settings)
        return Response(response.data)
