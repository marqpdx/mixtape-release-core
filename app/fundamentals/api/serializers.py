# fundamentals/api/serializers.py
"""
Serializers for Phase 4 Workbench API (Review Queue, MillDrafts).
"""

from rest_framework import serializers
from fundamentals.models import (
    MillDraft,
    MillDraftStatus,
    ContentProfileConfig,
    PublishSafetyClass,
    FieldRiskClass,
)


class MillDraftListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for Review Queue listing.
    """
    sponsor_type = serializers.CharField(read_only=True)
    sponsor_id = serializers.UUIDField(read_only=True)
    author_display_name = serializers.SerializerMethodField()
    source_display_name = serializers.SerializerMethodField()
    has_validation_errors = serializers.SerializerMethodField()

    class Meta:
        model = MillDraft
        fields = [
            'id',
            'status',
            'content_profile',
            'title',
            'summary',
            'source_type',
            'source_id',
            'source_display_name',
            'sponsor_type',
            'sponsor_id',
            'author',
            'author_name',
            'author_display_name',
            'is_valid',
            'has_validation_errors',
            'created_at',
            'updated_at',
            'status_changed_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status_changed_at']

    def get_author_display_name(self, obj):
        """Get display name for author"""
        if obj.author_name:
            return obj.author_name
        if obj.author:
            return obj.author.get_full_name() or obj.author.email
        return "Unknown"

    def get_source_display_name(self, obj):
        """Get friendly source name"""
        source_names = {
            'stackroom': 'Stackroom',
            'concord': 'Concord',
            'gristmill': 'Grist Mill',
            'copydesk': 'Copy Desk',
            'in-editor': 'In-Editor',
            'manual': 'Manual',
        }
        return source_names.get(obj.source_type, obj.source_type.title())

    def get_has_validation_errors(self, obj):
        """Check if draft has validation errors"""
        return len(obj.validation_errors) > 0


class MillDraftDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for editing and detailed view.
    """
    sponsor_type = serializers.CharField(read_only=True)
    sponsor_id = serializers.UUIDField(read_only=True)
    validation_errors = serializers.ReadOnlyField()
    validation_warnings = serializers.ReadOnlyField()
    canonical_object_type = serializers.SerializerMethodField()

    class Meta:
        model = MillDraft
        fields = [
            'id',
            'status',
            'content_profile',
            'title',
            'summary',
            'grist_body',
            'ast',
            'ast_generation_error',
            'source_type',
            'source_id',
            'provenance_bundle',
            'sponsor_type',
            'sponsor_id',
            'author',
            'author_name',
            'submitted_by',
            'canonical_content_type',
            'canonical_object_id',
            'canonical_object_type',
            'canonical_version',
            'validation_state',
            'validation_last_run',
            'validation_errors',
            'validation_warnings',
            'is_valid',
            'created_at',
            'updated_at',
            'status_changed_at',
            'promoted_at',
            'promoted_by',
            'archived_at',
            'archived_by',
        ]
        read_only_fields = [
            'id',
            'sponsor_type',
            'sponsor_id',
            'validation_errors',
            'validation_warnings',
            'is_valid',
            'created_at',
            'updated_at',
            'status_changed_at',
            'promoted_at',
            'promoted_by',
            'archived_at',
            'archived_by',
        ]

    def get_canonical_object_type(self, obj):
        """Get canonical object type name"""
        if obj.canonical_content_type:
            return obj.canonical_content_type.model
        return None


class MillDraftCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new MillDrafts.
    """
    sponsor_type = serializers.ChoiceField(
        choices=['user', 'group'],
        write_only=True,
        help_text="Type of sponsor (user or group)"
    )
    sponsor_id = serializers.UUIDField(
        write_only=True,
        help_text="UUID of sponsor object"
    )

    class Meta:
        model = MillDraft
        fields = [
            'sponsor_type',
            'sponsor_id',
            'content_profile',
            'title',
            'summary',
            'grist_body',
            'ast',
            'source_type',
            'source_id',
            'provenance_bundle',
            'author',
            'author_name',
            'canonical_content_type',
            'canonical_object_id',
            'canonical_version',
        ]

    def create(self, validated_data):
        """Create MillDraft with sponsor context"""
        from django.contrib.contenttypes.models import ContentType

        sponsor_type = validated_data.pop('sponsor_type')
        sponsor_id = validated_data.pop('sponsor_id')

        # Get ContentType for sponsor
        if sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            sponsor_ct = ContentType.objects.get_for_model(User)
        elif sponsor_type == 'group':
            from groups.models import Group
            sponsor_ct = ContentType.objects.get_for_model(Group)
        else:
            raise serializers.ValidationError(f"Invalid sponsor_type: {sponsor_type}")

        # Create MillDraft
        draft = MillDraft.objects.create(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
            status=MillDraftStatus.CANDIDATE,
            **validated_data
        )

        return draft


class MillDraftUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating MillDrafts (editing).
    """
    class Meta:
        model = MillDraft
        fields = [
            'title',
            'summary',
            'grist_body',
            'ast',
            'author_name',
        ]

    def update(self, instance, validated_data):
        """Update draft and run validation"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # Run soft validation on save
        instance.run_validation(hard=False)

        return instance


class MillDraftActionSerializer(serializers.Serializer):
    """
    Serializer for applying actions to MillDrafts.
    """
    action = serializers.ChoiceField(
        choices=['discard', 'approve', 'open', 'promote', 'archive', 'reactivate'],
        help_text="Action to perform"
    )

    def validate(self, data):
        """Validate action is allowed for current state"""
        draft = self.context.get('draft')
        action = data['action']

        if not draft:
            raise serializers.ValidationError("Draft context required")

        # Check if action is valid for current state
        if action == 'open' and not draft.is_candidate:
            raise serializers.ValidationError("Only candidate drafts can be opened")
        elif action == 'promote' and not draft.is_ready_to_promote:
            raise serializers.ValidationError("Only ready drafts can be promoted")
        elif action == 'reactivate' and not draft.is_archived:
            raise serializers.ValidationError("Only archived drafts can be reactivated")

        return data


class ContentProfileConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for Content Profile Configuration.
    """
    class Meta:
        model = ContentProfileConfig
        fields = [
            'id',
            'profile_name',
            'display_name',
            'description',
            'publish_safety_class',
            'field_risk_rules',
            'validation_schema',
            'required_fields',
            'is_enabled',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
