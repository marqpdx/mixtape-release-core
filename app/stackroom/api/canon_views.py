# stackroom/api/canon_views.py
"""
Canon governance API views (Puddlejump v1 Sections 4-6, Appendix A1/A4/A6).
"""
from __future__ import annotations

from django.http import FileResponse
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated

from stackroom.models import Library, SourceFile, SourceFileVersion
from stackroom.services import canon_service


class VersionListCreateView(APIView):
    """
    GET  /api/stackroom/source-files/<uuid>/versions — List version history
    POST /api/stackroom/source-files/<uuid>/versions — Submit new version
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile, id=source_file_id)
        versions = canon_service.get_version_history(source_file)
        return Response({"versions": versions})

    def post(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile, id=source_file_id)

        content = request.data.get("content", "")
        change_summary = request.data.get("change_summary", "")
        ai_assisted = request.data.get("ai_assisted", False)
        ai_agent = request.data.get("ai_agent", "")
        ai_summary = request.data.get("ai_summary", "")

        if not content:
            return Response(
                {"error": "content is required"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        version = canon_service.submit_version(
            source_file=source_file,
            content=content,
            actor=request.user,
            change_summary=change_summary,
            ai_assisted=ai_assisted,
            ai_agent=ai_agent,
            ai_summary=ai_summary,
        )

        return Response({
            "id": str(version.id),
            "version_number": version.version_number,
            "hash_sha256": version.hash_sha256,
            "created_at": version.created_at.isoformat(),
        }, status=drf_status.HTTP_201_CREATED)


class CanonApproveView(APIView):
    """
    POST /api/stackroom/source-files/<uuid>/approve — Approve a version as Canon
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, source_file_id):
        source_file = get_object_or_404(
            SourceFile.objects.select_related("library"),
            id=source_file_id,
        )

        version_id = request.data.get("version_id")
        notes = request.data.get("notes", "")

        if not version_id:
            return Response(
                {"error": "version_id is required"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        version = get_object_or_404(
            SourceFileVersion,
            id=version_id,
            source_file=source_file,
        )

        # TODO: Permission check — user must be group admin or have canApproveCanon
        # For v1, any authenticated user with access can approve

        approval = canon_service.approve_canon(
            source_file=source_file,
            version=version,
            approved_by=request.user,
            notes=notes,
        )

        # Trigger async ingestion (A4 — approval is synchronous, ingestion is async)
        try:
            from stackroom.tasks.processing import process_pending_uploads
            process_pending_uploads.delay()
        except Exception:
            pass  # Ingestion failure should not block approval

        return Response({
            "id": str(approval.id),
            "approved_at": approval.approved_at.isoformat(),
            "source_file_id": str(source_file.id),
            "version_id": str(version.id),
            "is_canon": True,
        })


class CanonDiffView(APIView):
    """
    GET /api/stackroom/source-files/<uuid>/diff — Get diff data for approval UI (A6)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        source_file = get_object_or_404(
            SourceFile.objects.select_related("canon_version"),
            id=source_file_id,
        )
        diff_data = canon_service.get_diff_versions(source_file)
        return Response(diff_data)


class CheckoutView(APIView):
    """
    POST /api/stackroom/source-files/<uuid>/checkout — Soft checkout (A1)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        source_file = get_object_or_404(
            SourceFile.objects.select_related("checked_out_by"),
            id=source_file_id,
        )
        checkout_status = canon_service.get_checkout_status(source_file, request_user=request.user)
        return Response({"checkout": checkout_status})

    def post(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile, id=source_file_id)
        canon_service.checkout(source_file, request.user)
        return Response({
            "checked_out_by": request.user.username,
            "checked_out_at": source_file.checked_out_at.isoformat(),
        })


class CheckinView(APIView):
    """
    POST /api/stackroom/source-files/<uuid>/checkin — Release checkout
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile, id=source_file_id)
        canon_service.checkin(source_file, request.user)
        return Response({"checked_out_by": None, "checked_out_at": None})


class LibraryExportView(APIView):
    """
    GET /api/stackroom/libraries/<uuid>/export — Download Canon bundle as zip (§7, §10)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        library = get_object_or_404(Library, id=library_id)

        include_non_canonical = request.query_params.get(
            "include_non_canonical", "false"
        ).lower() == "true"

        from stackroom.services.puddlejump_export import export_bundle
        zip_buffer = export_bundle(library, include_non_canonical=include_non_canonical)

        filename = f"{library.slug or 'puddlejump'}-export.zip"
        response = FileResponse(
            zip_buffer,
            content_type="application/zip",
            as_attachment=True,
            filename=filename,
        )
        return response
