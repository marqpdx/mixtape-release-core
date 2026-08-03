# groups/api/page_views.py
#
# Crossroads Page management endpoints (DB-0002).
# All write endpoints require Steward or above (IsGroupStewardOrAbove).
# The public read endpoint is in public_api/views.py.

from django.shortcuts import get_object_or_404
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.api.permissions import IsGroupStewardOrAbove
from groups.models import Group
from groups.models.public_page import PublicPage
from groups.page_slots import render_group_slots


# --- Serializers ---

class PublicPageSerializer(drf_serializers.ModelSerializer):
    group_slug = drf_serializers.CharField(source="group.slug", read_only=True)

    class Meta:
        model = PublicPage
        fields = [
            "id",
            "group_slug",
            "status",
            "draft_content",
            "published_content",
            "created_at",
            "updated_at",
            "published_at",
        ]
        read_only_fields = [
            "id",
            "group_slug",
            "status",
            "published_content",
            "created_at",
            "updated_at",
            "published_at",
        ]


# --- Views ---

class PublicPageView(APIView):
    """
    GET  /api/groups/<slug>/public-page  — fetch the page (draft + status)
    POST /api/groups/<slug>/public-page  — create the page (or refresh draft from Group fields)
    """
    permission_classes = [IsGroupStewardOrAbove]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists for this group."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicPageSerializer(page).data)

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
            created = False
        except PublicPage.DoesNotExist:
            page = PublicPage(group=group)
            created = True

        # Refresh draft_content from live Group DB fields
        page.draft_content = render_group_slots(group)
        page.save()

        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(PublicPageSerializer(page).data, status=http_status)


class PublicPageUpdateView(APIView):
    """
    PATCH /api/groups/<slug>/public-page/draft — update draft_content slots
    """
    permission_classes = [IsGroupStewardOrAbove]

    def patch(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists. POST to create it first."}, status=status.HTTP_404_NOT_FOUND)

        if page.status == PublicPage.Status.ARCHIVED:
            return Response({"detail": "Cannot edit an archived page."}, status=status.HTTP_400_BAD_REQUEST)

        slot_updates = request.data.get("draft_content", {})
        if not isinstance(slot_updates, dict):
            return Response({"detail": "'draft_content' must be an object."}, status=status.HTTP_400_BAD_REQUEST)

        page.draft_content = {**page.draft_content, **slot_updates}
        page.save(update_fields=["draft_content", "updated_at"])
        return Response(PublicPageSerializer(page).data)


class PublicPageSubmitView(APIView):
    """
    POST /api/groups/<slug>/public-page/submit — move draft → pending_approval
    """
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        try:
            page.submit_for_approval()
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PublicPageSerializer(page).data)


class PublicPagePublishView(APIView):
    """
    POST /api/groups/<slug>/public-page/publish — approve and publish
    """
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        page.publish()
        return Response(PublicPageSerializer(page).data)


class PublicPageArchiveView(APIView):
    """
    POST /api/groups/<slug>/public-page/archive — archive a published page
    """
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        try:
            page.archive()
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PublicPageSerializer(page).data)
