from __future__ import annotations

from rest_framework import serializers

from feedback.models import FeedbackBeacon, FeedbackItem, FeedbackAttachment


class FeedbackBeaconSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackBeacon
        fields = (
            "key",
            "title",
            "body_markdown",
            "feature_context",
            "scope",
            "route_pattern",
            "is_active",
            "start_at",
            "end_at",
        )


class FeedbackItemCreateSerializer(serializers.ModelSerializer):
    beacon_key = serializers.CharField(write_only=True)
    voice_file_id = serializers.UUIDField(required=False, allow_null=True)
    media_capture_id = serializers.UUIDField(required=False, allow_null=True)
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, default=list
    )

    class Meta:
        model = FeedbackItem
        fields = (
            "beacon_key",
            "kind",
            "message",
            "page_url",
            "work_area",
            "voice_file_id",
            "voice_transcript",
            "media_capture_id",
            "attachment_ids",
        )

    def validate(self, attrs):
        if not attrs.get("message"):
            raise serializers.ValidationError({"message": "Message is required"})
        return attrs


class FeedbackAttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    file_name = serializers.CharField(source="stored_file.file_name", read_only=True)

    class Meta:
        model = FeedbackAttachment
        fields = ("id", "url", "file_name", "created_at")

    def get_url(self, obj):
        return obj.stored_file.url


class FeedbackItemListSerializer(serializers.ModelSerializer):
    beacon_key = serializers.CharField(source="beacon.key", read_only=True)
    beacon_title = serializers.CharField(source="beacon.title", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    attachments = FeedbackAttachmentSerializer(many=True, read_only=True)
    voice_file_url = serializers.SerializerMethodField()
    media_capture_id = serializers.UUIDField(source="media_capture_id", read_only=True)

    class Meta:
        model = FeedbackItem
        fields = (
            "id",
            "beacon_key",
            "beacon_title",
            "kind",
            "message",
            "page_url",
            "work_area",
            "voice_transcript",
            "voice_file_url",
            "media_capture_id",
            "attachments",
            "status",
            "created_at",
            "user_username",
            "user_first_name",
        )

    def get_voice_file_url(self, obj):
        if obj.voice_file:
            return obj.voice_file.url
        return None
