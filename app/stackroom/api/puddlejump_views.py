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

from stackroom.api.puddlejump_serializers import (
    PuddlejumpImportSerializer,
    PuddlejumpImportResponseSerializer,
)
from stackroom.services.puddlejump_import import PuddlejumpImportService

logger = logging.getLogger(__name__)


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

                # Calculate total size
                total_size = sum(
                    zip_ref.getinfo(f).file_size
                    for f in markdown_files
                )

                # Success
                return {
                    "valid": True,
                    "bundle_id": manifest.get('bundle', {}).get('id', 'unknown'),
                    "manifest": manifest,
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                    "errors": []
                }

        finally:
            # Cleanup temp file
            Path(temp_zip_path).unlink(missing_ok=True)


class PuddlejumpHealthView(APIView):
    """
    Health check endpoint for Puddlejump API.

    GET /api/stackroom/puddlejump/health

    Returns:
        {
            "status": "ok",
            "version": "1.0.0",
            "phase": "Phase 1: Validation only"
        }
    """
    permission_classes = []  # Public endpoint

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "version": "1.0.0",
                "phase": "Phase 1: Validation only",
                "endpoints": {
                    "import": "/api/stackroom/puddlejump/import/",
                    "health": "/api/stackroom/puddlejump/health"
                }
            },
            status=drf_status.HTTP_200_OK
        )
