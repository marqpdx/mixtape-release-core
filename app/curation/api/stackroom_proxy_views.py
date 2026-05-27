from __future__ import annotations

from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.http import Http404, HttpResponse
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from curation.api.views import _check_read, _get_group_membership
from curation.models import Collection
from inkwell.stackroom_http_client import (
    StackroomClientError,
    download_source_file,
    get_source_file_metadata,
    get_source_file_readable,
)


def _stackroom_error_response(exc: StackroomClientError) -> Response:
    if exc.status_code == 404:
        return Response({"detail": "Source file not found."}, status=drf_status.HTTP_404_NOT_FOUND)
    return Response({"detail": exc.detail}, status=drf_status.HTTP_502_BAD_GATEWAY)


def _user_can_access_source_file(user, source_file_id: UUID, metadata: dict) -> bool:
    if user.is_staff or user.is_superuser:
        return True

    library_id = metadata.get("library_id")
    if not library_id:
        return False
    library_id = str(library_id)

    if str(getattr(user, "stackroom_library_id", "") or "") == library_id:
        return True

    from groups.models import Group

    group = Group.objects.filter(stackroom_library_id=library_id).first()
    if group is None:
        return False

    group_ct = ContentType.objects.get_for_model(Group)
    collections = (
        Collection.objects
        .filter(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            items__content_type__isnull=True,
            items__content_object_id=source_file_id,
        )
        .distinct()
    )
    for collection in collections:
        try:
            _check_read(user, collection)
            return True
        except Http404:
            continue

    if getattr(group, "visibility", "") == "public":
        return True

    return _get_group_membership(user, group.id) is not None


def _authorized_metadata_or_response(user, source_file_id: UUID) -> tuple[dict | None, Response | None]:
    try:
        metadata = get_source_file_metadata(source_file_id)
    except StackroomClientError as exc:
        return None, _stackroom_error_response(exc)

    if not _user_can_access_source_file(user, source_file_id, metadata):
        return None, Response({"detail": "Not authorized."}, status=drf_status.HTTP_403_FORBIDDEN)

    return metadata, None


class StackroomSourceFileReadableProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id: UUID):
        _, error_response = _authorized_metadata_or_response(request.user, source_file_id)
        if error_response is not None:
            return error_response

        try:
            return Response(get_source_file_readable(source_file_id))
        except StackroomClientError as exc:
            return _stackroom_error_response(exc)


class StackroomSourceFileDownloadProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id: UUID):
        _, error_response = _authorized_metadata_or_response(request.user, source_file_id)
        if error_response is not None:
            return error_response

        try:
            content, headers = download_source_file(source_file_id)
        except StackroomClientError as exc:
            return _stackroom_error_response(exc)

        response = HttpResponse(
            content,
            content_type=headers.get("content-type", "application/octet-stream"),
        )
        if headers.get("content-disposition"):
            response["Content-Disposition"] = headers["content-disposition"]
        return response
