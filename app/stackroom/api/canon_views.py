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

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from django.db.models import OuterRef, Subquery

from stackroom.models import Library, SourceFile, SourceFileVersion, IngestionRun
from stackroom.services import canon_service


def _user_can_access_library(user, library: Library) -> bool:
    """
    Return True if user may access this library at all (read or write).

    - Personal library (sponsor = User): only the sponsoring user.
    - Group library (sponsor = Group): any active, non-pending member.
    """
    if not library.sponsor_content_type:
        return False

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)

    if library.sponsor_content_type == user_ct:
        return str(user.pk) == str(library.sponsor_object_id)

    from groups.models import GroupMembership
    member_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group_id=library.sponsor_object_id,
        member_content_type=member_ct,
        member_object_id=user.pk,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).exists()


def _can_approve_canon(user, library: Library) -> bool:
    """
    Return True if user may approve a Canon version for this library.

    Spec §4.1: must be Group Admin or a user with canApproveCanon permission.

    - Personal library (sponsor = User): only the sponsoring user may approve.
    - Group library (sponsor = Group): user must be admin or owner of that group.
    """
    if not library.sponsor_content_type:
        return False

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)

    if library.sponsor_content_type == user_ct:
        # Personal library — sponsor is a user
        return str(user.pk) == str(library.sponsor_object_id)

    # Group library — check membership role
    from groups.models import GroupMembership
    member_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group_id=library.sponsor_object_id,
        member_content_type=member_ct,
        member_object_id=user.pk,
        is_active=True,
        roles__overlap=['admin', 'owner'],
    ).exists()


class VersionListCreateView(APIView):
    """
    GET  /api/stackroom/source-files/<uuid>/versions — List version history
    POST /api/stackroom/source-files/<uuid>/versions — Submit new version
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile.objects.select_related("library__sponsor_content_type"), id=source_file_id)
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)
        versions = canon_service.get_version_history(source_file)
        return Response({"versions": versions})

    def post(self, request, source_file_id):
        source_file = get_object_or_404(SourceFile.objects.select_related("library__sponsor_content_type"), id=source_file_id)
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)

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
        # Keep access checks opaque (404) before permission-specific checks.
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)

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

        if not _can_approve_canon(request.user, source_file.library):
            return Response(
                {"error": "You do not have permission to approve Canon for this library."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        approval = canon_service.approve_canon(
            source_file=source_file,
            version=version,
            approved_by=request.user,
            notes=notes,
        )

        # Trigger async ingestion (A4 — approval is synchronous, ingestion is async)
        # NOTE: process_pending_uploads is a batch task — it picks up all unprocessed files,
        # not just this one. A targeted per-file task would be cleaner but doesn't exist yet.
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
            SourceFile.objects.select_related("canon_version", "library__sponsor_content_type"),
            id=source_file_id,
        )
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)
        diff_data = canon_service.get_diff_versions(source_file)
        return Response(diff_data)


class CheckoutView(APIView):
    """
    POST /api/stackroom/source-files/<uuid>/checkout — Soft checkout (A1)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        source_file = get_object_or_404(
            SourceFile.objects.select_related("checked_out_by", "library__sponsor_content_type"),
            id=source_file_id,
        )
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)
        checkout_status = canon_service.get_checkout_status(source_file, request_user=request.user)
        return Response({"checkout": checkout_status})

    def post(self, request, source_file_id):
        source_file = get_object_or_404(
            SourceFile.objects.select_related("library__sponsor_content_type"),
            id=source_file_id,
        )
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)
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
        source_file = get_object_or_404(
            SourceFile.objects.select_related("library__sponsor_content_type"),
            id=source_file_id,
        )
        if not _user_can_access_library(request.user, source_file.library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)
        canon_service.checkin(source_file, request.user)
        return Response({"checked_out_by": None, "checked_out_at": None})


class LibraryExportView(APIView):
    """
    GET /api/stackroom/libraries/<uuid>/export — Download Canon bundle as zip (§7, §10)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        library = get_object_or_404(Library.objects.select_related("sponsor_content_type"), id=library_id)
        if not _user_can_access_library(request.user, library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)

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
        response["X-Bundle-Id"] = str(library.puddlejump_bundle_id or library.id)
        return response


class LibraryStatusView(APIView):
    """
    GET /api/stackroom/libraries/<uuid>/status

    Returns ingestion status, canonical file count, and bundle warnings
    for a library. Implements the deferred D5 status endpoint (contract §11.2).

    Response:
        {
            "library_id": "uuid",
            "bundle_id": "uuid | null",
            "file_count": 47,
            "canonical_count": 12,
            "ingestion_status": {
                "ready": 40,
                "processing": 5,
                "failed": 2,
                "pending": 0
            },
            "last_sync": "iso8601 | null",
            "warnings": [...]
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        library = get_object_or_404(Library.objects.select_related("sponsor_content_type"), id=library_id)
        if not _user_can_access_library(request.user, library):
            return Response({"error": "Not found"}, status=drf_status.HTTP_404_NOT_FOUND)

        # Latest ingestion run status per source file (subquery)
        latest_run_status = (
            IngestionRun.objects
            .filter(source_file=OuterRef("pk"))
            .order_by("-started_at")
            .values("status")[:1]
        )

        source_files = (
            SourceFile.objects
            .filter(library=library)
            .annotate(latest_status=Subquery(latest_run_status))
        )

        file_count = 0
        canonical_count = 0
        ingestion_buckets = {"ready": 0, "processing": 0, "failed": 0, "pending": 0}

        for sf in source_files:
            file_count += 1
            if sf.is_canon:
                canonical_count += 1

            status = sf.latest_status or "pending"
            if status in ("success", "partial"):
                ingestion_buckets["ready"] += 1
            elif status == "running":
                ingestion_buckets["processing"] += 1
            elif status == "failed":
                ingestion_buckets["failed"] += 1
            else:
                ingestion_buckets["pending"] += 1

        # Warnings
        warnings = []
        if file_count > 0 and canonical_count == 0:
            warnings.append({
                "code": "WARN_NO_CANONICAL",
                "message": "No files have been marked canonical",
            })
        if file_count > 250:
            warnings.append({
                "code": "WARN_APPROACHING_LIMIT",
                "message": f"Approaching 300-file limit ({file_count} files)",
                "file_count": file_count,
            })

        return Response({
            "library_id": str(library.id),
            "bundle_id": str(library.puddlejump_bundle_id) if library.puddlejump_bundle_id else None,
            "file_count": file_count,
            "canonical_count": canonical_count,
            "ingestion_status": ingestion_buckets,
            "last_sync": library.puddlejump_exported_at.isoformat() if library.puddlejump_exported_at else None,
            "warnings": warnings,
        })
