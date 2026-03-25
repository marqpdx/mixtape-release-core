# workbench/api/serializers.py

from rest_framework import serializers

from workbench.models import WorkingItem, WorkingItemMembership


class WorkingItemMembershipSerializer(serializers.ModelSerializer):
    type_label = serializers.SerializerMethodField()

    class Meta:
        model = WorkingItemMembership
        fields = [
            "id",
            "piece_content_type",
            "piece_object_id",
            "type_label",
            "content_snapshot",
            "position",
            "created_at",
        ]
        read_only_fields = ["id", "content_snapshot", "created_at"]

    def get_type_label(self, obj):
        return obj.piece_content_type.model if obj.piece_content_type_id else ""


class WorkingItemSerializer(serializers.ModelSerializer):
    memberships = WorkingItemMembershipSerializer(many=True, read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = WorkingItem
        fields = [
            "id",
            "slug",
            "title",
            "summary",
            "body_json",
            "status",
            "target_writing_kind",
            "body_editing_started",
            "spellcheck_passed",
            "spellcheck_passed_at",
            "promotion_gates",
            "promoted_to",
            "promoted_at",
            "last_saved_at",
            "auto_save_count",
            "author_username",
            "memberships",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "body_editing_started",
            "spellcheck_passed_at",
            "promoted_to",
            "promoted_at",
            "last_saved_at",
            "auto_save_count",
            "author_username",
            "memberships",
            "created_at",
            "updated_at",
        ]


class WorkingItemListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — no memberships."""
    author_username = serializers.CharField(source="author.username", read_only=True)
    membership_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkingItem
        fields = [
            "id",
            "slug",
            "title",
            "status",
            "target_writing_kind",
            "spellcheck_passed",
            "author_username",
            "membership_count",
            "last_saved_at",
            "created_at",
            "updated_at",
        ]

    def get_membership_count(self, obj):
        return obj.memberships.count()


class AutosaveSerializer(serializers.Serializer):
    """Payload for the autosave endpoint."""
    body_json = serializers.JSONField(required=False)
    title = serializers.CharField(required=False, allow_blank=True, max_length=100)
