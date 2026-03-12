# stackroom/api/puddlejump_views.py

from __future__ import annotations

import json
import zipfile
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication

from django.contrib.contenttypes.models import ContentType

from stackroom.api.puddlejump_serializers import (
    PuddlejumpImportSerializer,
    PuddlejumpImportResponseSerializer,
)
from stackroom.services.puddlejump_import import PuddlejumpImportService
from stackroom.models import Library, LibraryItem

logger = logging.getLogger(__name__)


def _get_or_create_personal_puddlejump(user):
    """Return the user's personal Puddlejump Library, creating it if absent."""
    user_ct = ContentType.objects.get_for_model(user)
    puddlejump = Library.objects.filter(
        sponsor_content_type=user_ct,
        sponsor_object_id=str(user.pk),
        is_personal_puddlejump=True,
    ).first()
    if not puddlejump:
        puddlejump = Library(
            title="My Puddlejump",
            summary="Your canonical archive. The things you stand behind.",
            body=(
                "Puddlejump is intentionally small, intentionally portable, "
                "intentionally human-governed. Files here sync with your filesystem, "
                "can be versioned in git, and are always exportable. Nothing is trapped."
            ),
            is_personal_puddlejump=True,
            puddlejump_origin='created',
        )
        puddlejump.set_sponsor(user)
        puddlejump.author = user
        puddlejump.submitted_by = user
        puddlejump.save()
        logger.info(f"Created personal Puddlejump for user {user.id}: {puddlejump.id}")
    return puddlejump


class PersonalPuddlejumpView(APIView):
    """
    Get or create the user's personal Puddlejump library.

    GET /api/stackroom/puddlejump/personal

    Returns the user's personal Puddlejump library with its items.
    If the user doesn't have a personal Puddlejump yet, one is created.

    Response:
        {
            "id": "uuid",
            "title": "My Puddlejump",
            "slug": "puddlejump",
            "summary": "...",
            "file_count": 0,
            "total_size_bytes": 0,
            "last_synced_at": null,
            "items": [...]
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get or create the user's personal Puddlejump"""
        user = request.user
        personal_puddlejump = _get_or_create_personal_puddlejump(user)

        # Get items with their content
        items = LibraryItem.objects.filter(
            library=personal_puddlejump
        ).select_related('content_type').order_by('order_index', 'created_at')

        # Build items response
        items_data = []
        total_size = 0
        for item in items:
            item_data = {
                "id": str(item.id),
                "is_folder": item.is_folder,
                "title": item.title,
                "folder_path": item.folder_path,
                "tags": item.tags,
                "notes": item.notes,
                "is_featured": item.is_featured,
                "order_index": item.order_index,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }

            # Add content info if not a folder
            if not item.is_folder and item.content_object:
                content = item.content_object
                item_data["content_type"] = item.content_type.model
                item_data["content_id"] = str(item.content_object_id)

                # Get filename and size if it's a SourceFile
                if hasattr(content, 'filename'):
                    item_data["filename"] = content.filename
                if hasattr(content, 'size_bytes'):
                    item_data["size_bytes"] = content.size_bytes
                    total_size += content.size_bytes or 0
                elif hasattr(content, 'file_size'):
                    item_data["size_bytes"] = content.file_size
                    total_size += content.file_size or 0

                # Include source_file_id for Canon governance UI
                if item.content_type.model == 'sourcefile':
                    item_data["source_file_id"] = str(content.id)
                    # Include latest version ID if versions exist
                    if hasattr(content, 'versions'):
                        latest = content.versions.order_by('-version_number').values_list('id', flat=True).first()
                        if latest:
                            item_data["latest_version_id"] = str(latest)

            items_data.append(item_data)

        return Response({
            "id": str(personal_puddlejump.id),
            "title": personal_puddlejump.title,
            "slug": personal_puddlejump.slug,
            "summary": personal_puddlejump.summary,
            "body": personal_puddlejump.body,
            "file_count": len([i for i in items if not i.is_folder]),
            "total_size_bytes": total_size,
            "last_synced_at": personal_puddlejump.puddlejump_exported_at.isoformat() if personal_puddlejump.puddlejump_exported_at else None,
            "items": items_data,
            "created_at": personal_puddlejump.created_at.isoformat(),
            "updated_at": personal_puddlejump.updated_at.isoformat(),
        }, status=drf_status.HTTP_200_OK)


class PuddlejumpImportView(APIView):
    """
    API endpoint for importing Puddlejump bundles.

    Phase 2: Validation + Import Processing (creates Library/LibraryItems)

    POST /api/stackroom/puddlejump/import/

    Request:
        - file: .zip file (multipart/form-data)
        - conflict_strategy: 'replace' | 'version' | 'skip' (optional)
        - auto_ingest: true | false (optional)

    Response (success):
        {
            "library_id": "...",
            "library_slug": "...",
            "bundle_id": "...",
            "status": "completed",
            "counts": {...}
        }

    Response (validation failure):
        {
            "valid": false,
            "errors": [...]
        }
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        """Handle Puddlejump bundle upload and validation"""

        # Step 1: Validate request data
        serializer = PuddlejumpImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "valid": False,
                    "errors": serializer.errors
                },
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = serializer.validated_data['file']
        conflict_strategy = serializer.validated_data['conflict_strategy']
        auto_ingest = serializer.validated_data['auto_ingest']

        logger.info(
            f"Puddlejump import attempt: {uploaded_file.name} "
            f"({uploaded_file.size} bytes) by user {request.user.id}"
        )

        # Step 2: Validate zip structure
        try:
            validation_result = self._validate_bundle(uploaded_file)
        except Exception as e:
            logger.error(f"Bundle validation failed: {str(e)}", exc_info=True)
            return Response(
                {
                    "valid": False,
                    "errors": [{
                        "field": "file",
                        "message": f"Bundle validation failed: {str(e)}"
                    }]
                },
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        if not validation_result['valid']:
            return Response(
                {
                    "valid": False,
                    "errors": validation_result['errors']
                },
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Step 3: Process import (Phase 2: create Library/LibraryItems)
        try:
            # Get sponsor (for now, use the requesting user as sponsor)
            # In production, this should come from request (group context, etc.)
            sponsor = request.user

            # Create import service
            import_service = PuddlejumpImportService(
                user=request.user,
                sponsor=sponsor
            )

            # Reset file pointer (was read during validation)
            uploaded_file.seek(0)

            # Perform import
            import_result = import_service.import_bundle(
                zip_file=uploaded_file,
                manifest=validation_result['manifest'],
                conflict_strategy=conflict_strategy,
                auto_ingest=auto_ingest
            )

            logger.info(
                f"Import completed: library {import_result['library_id']} "
                f"created with {import_result['counts']['new_files']} items"
            )

            # Propagate large bundle warning (A2)
            if validation_result.get("warning"):
                import_result["warning"] = validation_result["warning"]

            return Response(import_result, status=drf_status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Import processing failed: {str(e)}", exc_info=True)
            return Response(
                {
                    "valid": False,
                    "errors": [{
                        "field": "import",
                        "message": f"Import failed: {str(e)}"
                    }]
                },
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _validate_bundle(self, uploaded_file) -> Dict[str, Any]:
        """
        Validate Puddlejump bundle structure.

        Checks:
        1. Valid zip file
        2. Contains puddlejump.json
        3. Contains PUDDLEJUMP.md
        4. Contains Documents/ directory
        5. File count ≤ 300
        6. All files in Documents/ are .md
        7. Manifest is valid JSON

        Returns:
            {
                "valid": bool,
                "bundle_id": str,
                "manifest": dict,
                "file_count": int,
                "total_size_bytes": int,
                "errors": list  # if valid=False
            }
        """
        errors = []

        # Create temp file for zip
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            # Write uploaded file to temp location
            for chunk in uploaded_file.chunks():
                temp_zip.write(chunk)
            temp_zip_path = temp_zip.name

        try:
            # Check 1: Valid zip file
            if not zipfile.is_zipfile(temp_zip_path):
                return {
                    "valid": False,
                    "errors": [{
                        "field": "file",
                        "message": "Uploaded file is not a valid zip archive"
                    }]
                }

            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()

                # Check 2: Contains puddlejump.json
                manifest_files = [f for f in file_list if f.endswith('puddlejump.json')]
                if not manifest_files:
                    errors.append({
                        "field": "manifest",
                        "message": "Missing puddlejump.json manifest file"
                    })
                    return {"valid": False, "errors": errors}

                manifest_path = manifest_files[0]

                # Check 3: Contains PUDDLEJUMP.md
                catalog_files = [f for f in file_list if f.endswith('PUDDLEJUMP.md')]
                if not catalog_files:
                    errors.append({
                        "field": "catalog",
                        "message": "Missing PUDDLEJUMP.md catalog file"
                    })
                    return {"valid": False, "errors": errors}

                # Check 4: Contains Documents/ directory
                documents_files = [f for f in file_list if 'Documents/' in f]
                if not documents_files:
                    errors.append({
                        "field": "structure",
                        "message": "Missing Documents/ directory"
                    })
                    return {"valid": False, "errors": errors}

                # Check 5: Parse and validate manifest JSON
                try:
                    manifest_content = zip_ref.read(manifest_path)
                    manifest = json.loads(manifest_content)
                except json.JSONDecodeError as e:
                    errors.append({
                        "field": "manifest",
                        "message": f"Invalid JSON in manifest: {str(e)}"
                    })
                    return {"valid": False, "errors": errors}

                # Check 6: Validate manifest has required fields
                required_fields = ['format_version', 'bundle', 'files', 'integrity']
                for field in required_fields:
                    if field not in manifest:
                        errors.append({
                            "field": "manifest",
                            "message": f"Missing required field in manifest: {field}"
                        })

                if errors:
                    return {"valid": False, "errors": errors}

                # Check 7: File count ≤ 300
                markdown_files = [
                    f for f in documents_files
                    if f.endswith('.md') and not f.endswith('/')
                ]
                file_count = len(markdown_files)

                if file_count > 300:
                    errors.append({
                        "field": "file_count",
                        "actual": file_count,
                        "max": 300,
                        "message": f"File count ({file_count}) exceeds maximum of 300"
                    })
                    return {"valid": False, "errors": errors}

                # Warning threshold at 100 files (Appendix A2)
                large_bundle_warning = file_count > 100

                # Check 8: All files in Documents/ are markdown
                non_markdown = [
                    f for f in documents_files
                    if not f.endswith('.md') and not f.endswith('/')
                ]
                if non_markdown:
                    errors.append({
                        "field": "file_format",
                        "message": f"Non-markdown files found in Documents/: {non_markdown[:5]}",
                        "count": len(non_markdown)
                    })
                    return {"valid": False, "errors": errors}

                # Check 9: Total size ≤ 50MB — measured by streaming, not zip metadata
                # zip header file_size is attacker-controlled and cannot be trusted (zip bomb vector)
                max_size_bytes = 50 * 1024 * 1024
                total_size = 0
                for f in markdown_files:
                    with zip_ref.open(f) as fh:
                        while True:
                            chunk = fh.read(65536)
                            if not chunk:
                                break
                            total_size += len(chunk)
                            if total_size > max_size_bytes:
                                return {
                                    "valid": False,
                                    "errors": [{
                                        "field": "total_size",
                                        "max": max_size_bytes,
                                        "message": "Bundle exceeds maximum size of 50MB"
                                    }]
                                }

                # Success
                result = {
                    "valid": True,
                    "bundle_id": manifest.get('bundle', {}).get('id', 'unknown'),
                    "manifest": manifest,
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                    "errors": []
                }
                if large_bundle_warning:
                    result["warning"] = "large_bundle"
                return result

        finally:
            # Cleanup temp file
            Path(temp_zip_path).unlink(missing_ok=True)


class PuddlejumpSyncStatusView(APIView):
    """
    Get sync status for desktop client.

    GET /api/stackroom/puddlejump/sync/status

    Returns list of all files with their hashes for client-side diffing.

    Response:
        {
            "library_id": "uuid",
            "last_synced_at": "iso8601",
            "files": [
                {
                    "id": "uuid",
                    "path": "relative/path.md",
                    "hash": "sha256:...",
                    "size_bytes": 1234,
                    "modified_at": "iso8601"
                }
            ]
        }
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        puddlejump = _get_or_create_personal_puddlejump(user)

        # Get all files (not folders)
        from stackroom.models import SourceFile
        items = LibraryItem.objects.filter(
            library=puddlejump,
            is_folder=False
        ).select_related('content_type')

        files = []
        for item in items:
            if item.content_type and item.content_type.model == 'sourcefile':
                try:
                    source_file = SourceFile.objects.get(id=item.content_object_id)
                    files.append({
                        "id": str(item.id),
                        "source_file_id": str(source_file.id),
                        "path": item.folder_path or source_file.filename,
                        "hash": f"sha256:{source_file.hash_sha256}" if source_file.hash_sha256 else None,
                        "size_bytes": source_file.size_bytes,
                        "modified_at": source_file.updated_at.isoformat(),
                    })
                except SourceFile.DoesNotExist:
                    pass

        return Response({
            "library_id": str(puddlejump.id),
            "last_synced_at": puddlejump.puddlejump_exported_at.isoformat() if puddlejump.puddlejump_exported_at else None,
            "file_count": len(files),
            "files": files,
        })


class PuddlejumpSyncUploadView(APIView):
    """
    Upload a file to personal Puddlejump.

    POST /api/stackroom/puddlejump/sync/upload

    Request (multipart/form-data):
        - file: The file to upload
        - path: Relative path in Puddlejump (e.g., "notes/ideas.md")
        - hash: SHA-256 hash of file content (for verification)

    Response:
        {
            "id": "uuid",
            "path": "notes/ideas.md",
            "hash": "sha256:...",
            "size_bytes": 1234,
            "created": true
        }
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        import hashlib
        from django.core.files.storage import default_storage
        from stackroom.models import SourceFile

        user = request.user

        # Get file and metadata
        uploaded_file = request.FILES.get('file')
        file_path = request.data.get('path', '')
        client_hash = request.data.get('hash', '')

        if not uploaded_file:
            return Response(
                {"error": "No file provided"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Enforce per-file size limit (5MB — single files should be well under this)
        max_file_bytes = 5 * 1024 * 1024
        if uploaded_file.size > max_file_bytes:
            return Response(
                {"error": "File exceeds maximum size of 5MB"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Sanitize path: reject traversal sequences and absolute paths
        normalized = Path(file_path).as_posix()
        if (
            not file_path
            or normalized.startswith('/')
            or any(part == '..' for part in Path(normalized).parts)
        ):
            return Response(
                {"error": "Invalid file path"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )
        file_path = normalized

        # Validate file is markdown
        if not file_path.endswith('.md'):
            return Response(
                {"error": "Only markdown files (.md) are allowed"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        puddlejump = _get_or_create_personal_puddlejump(user)

        # Read file content and compute hash
        content = uploaded_file.read()
        computed_hash = hashlib.sha256(content).hexdigest()
        uploaded_file.seek(0)

        # Verify hash if provided
        if client_hash and client_hash.replace('sha256:', '') != computed_hash:
            return Response(
                {"error": "Hash mismatch - file may be corrupted"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Check if file already exists at this path
        existing_item = LibraryItem.objects.filter(
            library=puddlejump,
            folder_path=file_path,
            is_folder=False
        ).first()

        if existing_item and existing_item.content_object:
            # Update existing file
            source_file = existing_item.content_object
            # Delete old file from storage
            if source_file.path and default_storage.exists(source_file.path):
                default_storage.delete(source_file.path)

            # Save new content
            storage_path = f"puddlejump/{user.id}/{file_path}"
            saved_path = default_storage.save(storage_path, uploaded_file)

            source_file.path = saved_path
            source_file.hash_sha256 = computed_hash
            source_file.size_bytes = len(content)
            source_file.save()

            created = False
        else:
            # Create new file
            storage_path = f"puddlejump/{user.id}/{file_path}"
            saved_path = default_storage.save(storage_path, uploaded_file)

            source_file = SourceFile.objects.create(
                library=puddlejump,
                filename=file_path.split('/')[-1],
                path=saved_path,
                content_type='text/markdown',
                size_bytes=len(content),
                hash_sha256=computed_hash,
            )

            # Create LibraryItem
            source_file_ct = ContentType.objects.get_for_model(SourceFile)
            LibraryItem.objects.create(
                library=puddlejump,
                content_type=source_file_ct,
                content_object_id=source_file.id,
                folder_path=file_path,
                is_folder=False,
            )

            created = True

        return Response({
            "id": str(source_file.id),
            "path": file_path,
            "hash": f"sha256:{computed_hash}",
            "size_bytes": len(content),
            "created": created,
        })


class PuddlejumpSyncDownloadView(APIView):
    """
    Download a file from personal Puddlejump.

    GET /api/stackroom/puddlejump/sync/download/<file_id>

    Returns the file content.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, file_id):
        from django.http import FileResponse
        from django.core.files.storage import default_storage
        from stackroom.models import SourceFile

        user = request.user
        user_ct = ContentType.objects.get_for_model(user)

        # Verify user owns this Puddlejump
        puddlejump = Library.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            is_personal_puddlejump=True
        ).first()

        if not puddlejump:
            return Response(
                {"error": "Puddlejump not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # Get the file
        try:
            source_file = SourceFile.objects.get(
                id=file_id,
                library=puddlejump
            )
        except SourceFile.DoesNotExist:
            return Response(
                {"error": "File not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # Return file content
        if not source_file.path or not default_storage.exists(source_file.path):
            return Response(
                {"error": "File content not found in storage"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        file_handle = default_storage.open(source_file.path, 'rb')
        response = FileResponse(
            file_handle,
            content_type='text/markdown',
            as_attachment=True,
            filename=source_file.filename
        )
        response['X-File-Hash'] = f"sha256:{source_file.hash_sha256}"
        return response


class PuddlejumpSyncDeleteView(APIView):
    """
    Delete a file from personal Puddlejump.

    DELETE /api/stackroom/puddlejump/sync/delete/<file_id>
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, file_id):
        from django.core.files.storage import default_storage
        from stackroom.models import SourceFile

        user = request.user
        user_ct = ContentType.objects.get_for_model(user)

        # Verify user owns this Puddlejump
        puddlejump = Library.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            is_personal_puddlejump=True
        ).first()

        if not puddlejump:
            return Response(
                {"error": "Puddlejump not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # Get the file
        try:
            source_file = SourceFile.objects.get(
                id=file_id,
                library=puddlejump
            )
        except SourceFile.DoesNotExist:
            return Response(
                {"error": "File not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # Delete from storage
        if source_file.path and default_storage.exists(source_file.path):
            default_storage.delete(source_file.path)

        # Delete LibraryItem
        source_file_ct = ContentType.objects.get_for_model(SourceFile)
        LibraryItem.objects.filter(
            library=puddlejump,
            content_type=source_file_ct,
            content_object_id=source_file.id
        ).delete()

        # Delete SourceFile
        source_file.delete()

        return Response({"deleted": True})


class PuddlejumpSyncCompleteView(APIView):
    """
    Mark sync as complete.

    POST /api/stackroom/puddlejump/sync/complete

    Updates last_synced_at timestamp.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)

        puddlejump = Library.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            is_personal_puddlejump=True
        ).first()

        if not puddlejump:
            return Response(
                {"error": "Puddlejump not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        puddlejump.puddlejump_exported_at = timezone.now()
        puddlejump.save()

        return Response({
            "synced_at": puddlejump.puddlejump_exported_at.isoformat()
        })


class PuddlejumpHealthView(APIView):
    """
    Health check endpoint for Puddlejump API.

    GET /api/stackroom/puddlejump/health

    Returns:
        {
            "status": "ok",
            "version": "1.0.0",
            "phase": "Phase 2: Sync support"
        }
    """
    permission_classes = []  # Public endpoint

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "version": "1.0.0",
                "phase": "Phase 2: Sync support",
                "endpoints": {
                    "personal": "/api/stackroom/puddlejump/personal",
                    "import": "/api/stackroom/puddlejump/import",
                    "sync_status": "/api/stackroom/puddlejump/sync/status",
                    "sync_upload": "/api/stackroom/puddlejump/sync/upload",
                    "sync_download": "/api/stackroom/puddlejump/sync/download/<file_id>",
                    "sync_delete": "/api/stackroom/puddlejump/sync/delete/<file_id>",
                    "sync_complete": "/api/stackroom/puddlejump/sync/complete",
                    "health": "/api/stackroom/puddlejump/health"
                }
            },
            status=drf_status.HTTP_200_OK
        )


# COMMENTED OUT — PuddlejumpAuthDebugView
# This view was a development-only tool for testing OAuth2 token validation.
# It had permission_classes = [] (fully open, no auth required) and exposed
# OAuth token counts, token previews, and internal DOT verification results —
# a security risk in any non-local environment.
#
# It is not called by any frontend code or tests.
# If OAuth debugging is needed, use the Django shell or a management command:
#
#   python manage.py shell
#   >>> from oauth2_provider.models import AccessToken
#   >>> AccessToken.objects.filter(token="...").first()
#
# Do not re-register this as a live endpoint.
#
# class PuddlejumpAuthDebugView(APIView):
#     """Temporary debug view — test OAuth2 token validation in isolation."""
#     authentication_classes = [OAuth2Authentication]
#     permission_classes = []  # Skip permission check, just test auth

#     def get(self, request):
#         from oauth2_provider.models import AccessToken as OAuthAccessToken
#         from django.utils import timezone as tz
#
#         auth_header = request.META.get("HTTP_AUTHORIZATION", "none")
#         token_str = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
#         token_count = OAuthAccessToken.objects.count()
#         token_obj = None
#         if token_str:
#             token_obj = OAuthAccessToken.objects.filter(token=token_str).first()
#         token_info = None
#         if token_obj:
#             token_info = {
#                 "user": str(token_obj.user),
#                 "application": str(token_obj.application),
#                 "expires": str(token_obj.expires),
#                 "is_expired": token_obj.expires < tz.now() if token_obj.expires else "no_expiry",
#                 "scope": token_obj.scope,
#                 "created": str(token_obj.created) if hasattr(token_obj, 'created') else "n/a",
#             }
#         dot_error = None
#         try:
#             from oauth2_provider.oauth2_backends import get_oauthlib_core
#             oauthlib_core = get_oauthlib_core()
#             valid, r = oauthlib_core.verify_request(request, scopes=[])
#             dot_result = {"valid": valid, "oauth2_error": getattr(r, "oauth2_error", {})}
#             if valid:
#                 dot_result["verified_user"] = str(r.user)
#         except Exception as e:
#             dot_result = {"error": str(e)}
#         return Response({
#             "user": str(request.user),
#             "is_authenticated": request.user.is_authenticated if hasattr(request.user, 'is_authenticated') else False,
#             "auth_header_present": auth_header != "none",
#             "token_preview": token_str[:20] + "..." if len(token_str) > 20 else token_str,
#             "total_oauth_tokens_in_db": token_count,
#             "token_in_db": token_info,
#             "dot_verify_request": dot_result,
#         })
