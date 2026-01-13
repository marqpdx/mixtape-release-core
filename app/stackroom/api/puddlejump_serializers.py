# stackroom/api/puddlejump_serializers.py

from __future__ import annotations

from rest_framework import serializers


class PuddlejumpImportSerializer(serializers.Serializer):
    """
    Serializer for Puddlejump bundle import requests.

    Validates the uploaded file and optional parameters.
    """
    file = serializers.FileField(
        help_text="Puddlejump bundle as .zip file"
    )
    conflict_strategy = serializers.ChoiceField(
        choices=['replace', 'version', 'skip'],
        required=False,
        default='replace',
        help_text="How to handle conflicts with existing files"
    )
    auto_ingest = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to trigger Stackroom ingestion automatically"
    )

    def validate_file(self, value):
        """Validate that uploaded file is a zip"""
        if not value.name.endswith('.zip'):
            raise serializers.ValidationError(
                "Only .zip files are supported. Please upload a Puddlejump bundle as .zip"
            )

        # Check file size (50MB max per spec)
        max_size = 52_428_800  # 50MB in bytes
        if value.size > max_size:
            raise serializers.ValidationError(
                f"Bundle size ({value.size} bytes) exceeds maximum of 50MB ({max_size} bytes)"
            )

        return value


class PuddlejumpValidationErrorSerializer(serializers.Serializer):
    """Serializer for validation error details"""
    field = serializers.CharField()
    actual = serializers.CharField(required=False, allow_null=True)
    max = serializers.IntegerField(required=False, allow_null=True)
    message = serializers.CharField()


class PuddlejumpImportResponseSerializer(serializers.Serializer):
    """
    Serializer for successful import response.

    Returned after validation passes and import begins.
    """
    library_id = serializers.UUIDField(
        help_text="UUID of created or updated Library"
    )
    library_slug = serializers.CharField(
        help_text="URL-friendly slug for the library"
    )
    bundle_id = serializers.CharField(
        help_text="Bundle ID from manifest"
    )
    status = serializers.ChoiceField(
        choices=['processing', 'conflicts_detected', 'completed', 'failed'],
        help_text="Current status of import operation"
    )
    counts = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="File counts (total, new, updated, skipped, conflicts)"
    )
    conflicts = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="List of file conflicts (present if status='conflicts_detected')"
    )
    ingestion_status = serializers.ChoiceField(
        choices=['queued', 'running', 'completed', 'failed'],
        required=False,
        help_text="Status of Stackroom ingestion (if auto_ingest=true)"
    )
    created_at = serializers.DateTimeField(
        help_text="ISO 8601 timestamp of import start"
    )
    error = serializers.CharField(
        required=False,
        help_text="Error message (present if status='failed')"
    )


class PuddlejumpExportSerializer(serializers.Serializer):
    """
    Serializer for Puddlejump bundle export requests.
    """
    format = serializers.ChoiceField(
        choices=['zip', 'folder'],
        required=False,
        default='zip',
        help_text="Output format for export"
    )
    include_non_canonical = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to include non-canonical files in export"
    )
    filename = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional custom filename for export"
    )


class PuddlejumpExportResponseSerializer(serializers.Serializer):
    """Serializer for export response"""
    bundle_id = serializers.CharField(
        help_text="New UUID generated for this export"
    )
    download_url = serializers.URLField(
        help_text="Signed temporary URL for download"
    )
    expires_at = serializers.DateTimeField(
        help_text="When the download URL expires"
    )
    bundle_info = serializers.DictField(
        help_text="Summary information about the bundle"
    )
