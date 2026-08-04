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
from groups.models.page_component import PageComponent
from groups.page_slots import render_group_slots


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class PublicPageSerializer(drf_serializers.ModelSerializer):
    group_slug = drf_serializers.CharField(source="group.slug", read_only=True)

    class Meta:
        model = PublicPage
        fields = [
            "id",
            "group_slug",
            "status",
            "layout_template",
            "needs_review",
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


class PageComponentSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = PageComponent
        fields = [
            "id",
            "slot",
            "component_type",
            "content_json",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ---------------------------------------------------------------------------
# PublicPage views
# ---------------------------------------------------------------------------

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

        page.draft_content = render_group_slots(group)
        page.save()

        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(PublicPageSerializer(page).data, status=http_status)


class PublicPageUpdateView(APIView):
    """
    PATCH /api/groups/<slug>/public-page/draft — update draft_content slots,
    layout_template, or needs_review flag.
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

        update_fields = ["updated_at"]

        slot_updates = request.data.get("draft_content")
        if slot_updates is not None:
            if not isinstance(slot_updates, dict):
                return Response({"detail": "'draft_content' must be an object."}, status=status.HTTP_400_BAD_REQUEST)
            page.draft_content = {**page.draft_content, **slot_updates}
            update_fields.append("draft_content")

        layout_template = request.data.get("layout_template")
        if layout_template is not None:
            valid = [c[0] for c in PublicPage.LayoutTemplate.choices]
            if layout_template not in valid:
                return Response({"detail": f"Invalid layout_template. Choices: {valid}"}, status=status.HTTP_400_BAD_REQUEST)
            page.layout_template = layout_template
            update_fields.append("layout_template")

        needs_review = request.data.get("needs_review")
        if needs_review is not None:
            if not isinstance(needs_review, bool):
                return Response({"detail": "'needs_review' must be a boolean."}, status=status.HTTP_400_BAD_REQUEST)
            page.needs_review = needs_review
            update_fields.append("needs_review")

        page.save(update_fields=update_fields)
        return Response(PublicPageSerializer(page).data)


class PublicPageSubmitView(APIView):
    """POST /api/groups/<slug>/public-page/submit — move draft → pending_approval"""
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
    """POST /api/groups/<slug>/public-page/publish — approve and publish"""
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        page.publish()
        return Response(PublicPageSerializer(page).data)


class PublicPageUnpublishView(APIView):
    """POST /api/groups/<slug>/public-page/unpublish — take page offline (published → draft)"""
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        try:
            page.unpublish()
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PublicPageSerializer(page).data)


class PublicPageArchiveView(APIView):
    """POST /api/groups/<slug>/public-page/archive — permanently retire a published page"""
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


# ---------------------------------------------------------------------------
# PageComponent views (ad hoc content)
# ---------------------------------------------------------------------------

class PageComponentListCreateView(APIView):
    """
    GET  /api/groups/<slug>/public-page/components       — list all ad hoc components
    POST /api/groups/<slug>/public-page/components       — create a new component
    """
    permission_classes = [IsGroupStewardOrAbove]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)

        components = page.components.all()
        return Response(PageComponentSerializer(components, many=True).data)

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response({"detail": "No public page exists. POST to create it first."}, status=status.HTTP_404_NOT_FOUND)

        if page.status == PublicPage.Status.ARCHIVED:
            return Response({"detail": "Cannot add components to an archived page."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PageComponentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(page=page)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PageComponentDetailView(APIView):
    """
    GET    /api/groups/<slug>/public-page/components/<id>  — fetch a component
    PATCH  /api/groups/<slug>/public-page/components/<id>  — update a component
    DELETE /api/groups/<slug>/public-page/components/<id>  — delete a component
    """
    permission_classes = [IsGroupStewardOrAbove]

    def _get_component(self, slug, component_id):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return None, None, Response({"detail": "No public page exists."}, status=status.HTTP_404_NOT_FOUND)
        component = get_object_or_404(PageComponent, id=component_id, page=page)
        return page, component, None

    def get(self, request, slug, component_id):
        _, component, err = self._get_component(slug, component_id)
        if err:
            return err
        return Response(PageComponentSerializer(component).data)

    def patch(self, request, slug, component_id):
        page, component, err = self._get_component(slug, component_id)
        if err:
            return err
        if page.status == PublicPage.Status.ARCHIVED:
            return Response({"detail": "Cannot edit components on an archived page."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PageComponentSerializer(component, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, slug, component_id):
        _, component, err = self._get_component(slug, component_id)
        if err:
            return err
        component.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
