# files/api/views.py

import logging

from django.core.files.storage import default_storage
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import StoredFile

logger = logging.getLogger(__name__)


class StoredFileServeView(APIView):
    """
    Stable redirect to a Stash-backed file.

    GET /api/files/<uuid:pk>/serve

    Presigned URLs from default_storage.url() expire, so they cannot be
    embedded directly in persisted content (e.g. inline images in a writing
    piece's body_json). This endpoint provides a permanent URL: it presigns
    the underlying Stash path at request time and issues a 302 redirect. The
    stored body_json only ever holds the /serve path, which never expires.

    AllowAny: the StoredFile UUID is unguessable and only surfaces inside
    content the requester already has access to; the presigned target is
    itself time-limited. This mirrors the AllowAny posture of the assets
    presign endpoint.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        stored = get_object_or_404(StoredFile, pk=pk)

        if not stored.file_path:
            return Response(
                {"detail": "File has no stored path."},
                status=status.HTTP_404_NOT_FOUND,
            )

        target = default_storage.url(stored.file_path)
        return HttpResponseRedirect(target)
