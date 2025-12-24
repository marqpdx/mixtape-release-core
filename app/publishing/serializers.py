# publishing/serializers.py

"""
Serializers for publishing models.
"""

from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from .models import ContentPlacement, PublicationGroup


class ContentPlacementSerializer(serializers.ModelSerializer):
    """Serializer for ContentPlacement."""

    # Human-readable fields
    source_type = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()
    locked_artifact_type = serializers.SerializerMethodField()

    class Meta:
        model = ContentPlacement
        fields = [
            'id',
            'created_at',
            'updated_at',
            'publication_group',
            'placed_by',

            # Source
            'source_content_type',
            'source_object_id',
            'source_type',

            # Target
            'target_content_type',
            'target_object_id',
            'target_type',

            # Channel and visibility
            'channel',
            'visibility',

            # Version behavior
            'follow_updates',
            'locked_artifact_content_type',
            'locked_artifact_object_id',
            'locked_artifact_type',

            # Display customization
            'is_excerpt',
            'fragment_selector',
            'overrides',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_source_type(self, obj):
        """Get human-readable source type."""
        if obj.source_content_type:
            return obj.source_content_type.model
        return None

    def get_target_type(self, obj):
        """Get human-readable target type."""
        if obj.target_content_type:
            return obj.target_content_type.model
        return None

    def get_locked_artifact_type(self, obj):
        """Get human-readable locked artifact type."""
        if obj.locked_artifact_content_type:
            return obj.locked_artifact_content_type.model
        return None


class PublicationGroupSerializer(serializers.ModelSerializer):
    """Serializer for PublicationGroup."""

    placements = ContentPlacementSerializer(many=True, read_only=True)
    source_type = serializers.SerializerMethodField()

    class Meta:
        model = PublicationGroup
        fields = [
            'id',
            'created_at',
            'created_by',
            'source_content_type',
            'source_object_id',
            'source_type',
            'note',
            'placements',
        ]
        read_only_fields = ['id', 'created_at']

    def get_source_type(self, obj):
        """Get human-readable source type."""
        if obj.source_content_type:
            return obj.source_content_type.model
        return None
