# groups/api/files_views.py

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status as drf_status

from groups.models import Group, GroupMembership


class GroupFilesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        from stackroom_client import (
            get_or_create_group_library,
            get_library_source_files,
            StackroomClientError,
        )

        group = get_object_or_404(Group, slug=slug)

        if not group.is_member(request.user):
            return Response({"detail": "You are not an active member of this group."}, status=drf_status.HTTP_403_FORBIDDEN)

        try:
            library_id = get_or_create_group_library(group)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        try:
            raw_files = get_library_source_files(library_id)
        except StackroomClientError:
            return Response([])

        files_data = [
            {
                "id": f["id"],
                "filename": f["filename"],
                "content_type": f["content_type"],
                "size_bytes": f["size_bytes"],
                "origin": f["origin"],
                "created_at": f["created_at"],
            }
            for f in raw_files
        ]

        return Response(files_data)


class GroupFileUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        from stackroom_client import (
            get_or_create_group_library,
            upload_library_file,
            StackroomClientError,
        )

        group = get_object_or_404(Group, slug=slug)

        user_ct = ContentType.objects.get_for_model(request.user.__class__)
        membership = group.memberships.filter(
            member_content_type=user_ct,
            member_object_id=request.user.pk,
            is_active=True,
            is_pending=False,
            is_banned=False,
            is_evicted=False,
        ).first()
        is_editor = membership and (
            membership.is_owner() or membership.is_admin() or membership.is_steward()
        )

        if not is_editor:
            return Response(
                {"detail": "You must be a group owner, admin, or steward to upload files."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "No file provided."}, status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            library_id = get_or_create_group_library(group)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        try:
            result = upload_library_file(
                library_id=library_id,
                file_bytes=uploaded.read(),
                filename=uploaded.name,
                content_type=uploaded.content_type or "application/octet-stream",
            )
        except StackroomClientError as exc:
            if exc.status_code == 409:
                return Response(
                    {
                        "detail": "File already exists in this library.",
                        "source_file_id": exc.extra.get("source_file_id"),
                    },
                    status=drf_status.HTTP_409_CONFLICT,
                )
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=drf_status.HTTP_201_CREATED)


class GroupFileDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, slug, source_file_id):
        from stackroom_client import (
            delete_source_file,
            StackroomClientError,
        )

        group = get_object_or_404(Group, slug=slug)

        user_ct = ContentType.objects.get_for_model(request.user.__class__)
        membership = group.memberships.filter(
            member_content_type=user_ct,
            member_object_id=request.user.pk,
            is_active=True,
            is_pending=False,
            is_banned=False,
            is_evicted=False,
        ).first()
        is_editor = membership and (
            membership.is_owner() or membership.is_admin() or membership.is_steward()
        )

        if not is_editor:
            return Response(
                {"detail": "You must be a group owner, admin, or steward to delete files."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        try:
            delete_source_file(source_file_id)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class GroupFileDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug, source_file_id):
        from stackroom_client import (
            download_source_file,
            StackroomClientError,
        )

        group = get_object_or_404(Group, slug=slug)

        if not group.is_member(request.user):
            return Response({"detail": "You are not an active member of this group."}, status=drf_status.HTTP_403_FORBIDDEN)

        try:
            content, headers = download_source_file(source_file_id)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        response = HttpResponse(
            content,
            content_type=headers.get("Content-Type", "application/octet-stream"),
        )
        if "Content-Disposition" in headers:
            response["Content-Disposition"] = headers["Content-Disposition"]
        return response


class GroupFilePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug, source_file_id):
        from stackroom_client import (
            preview_source_file_pdf,
            StackroomClientError,
        )

        group = get_object_or_404(Group, slug=slug)

        if not group.is_member(request.user):
            return Response({"detail": "You are not an active member of this group."}, status=drf_status.HTTP_403_FORBIDDEN)

        try:
            content, headers = preview_source_file_pdf(source_file_id)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        response = HttpResponse(
            content,
            content_type=headers.get("Content-Type", "application/pdf"),
        )
        if "Content-Disposition" in headers:
            response["Content-Disposition"] = headers["Content-Disposition"]
        return response


class MeFilesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from stackroom_client import (
            get_or_create_user_library,
            get_library_source_files,
            StackroomClientError,
        )

        try:
            library_id = get_or_create_user_library(request.user)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        try:
            raw_files = get_library_source_files(library_id)
        except StackroomClientError:
            return Response([])

        files_data = [
            {
                "id": f["id"],
                "filename": f["filename"],
                "content_type": f["content_type"],
                "size_bytes": f["size_bytes"],
                "origin": f["origin"],
                "created_at": f["created_at"],
            }
            for f in raw_files
        ]

        return Response(files_data)


class MeFileDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, source_file_id):
        from stackroom_client import (
            get_or_create_user_library,
            get_library_source_files,
            delete_source_file,
            StackroomClientError,
        )

        try:
            library_id = get_or_create_user_library(request.user)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        try:
            files = get_library_source_files(library_id)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        file_ids = {str(f["id"]) for f in files}
        if str(source_file_id) not in file_ids:
            return Response({"detail": "File not found in your library."}, status=drf_status.HTTP_404_NOT_FOUND)

        try:
            delete_source_file(source_file_id)
        except StackroomClientError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        return Response(status=drf_status.HTTP_204_NO_CONTENT)
