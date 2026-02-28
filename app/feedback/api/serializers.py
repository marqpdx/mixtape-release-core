from __future__ import annotations

from rest_framework import serializers

from feedback.models import FeedbackBeacon, FeedbackItem


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

    class Meta:
        model = FeedbackItem
        fields = ("beacon_key", "kind", "message", "page_url")

    def validate(self, attrs):
        if not attrs.get("message"):
            raise serializers.ValidationError({"message": "Message is required"})
        return attrs


class FeedbackItemListSerializer(serializers.ModelSerializer):
    beacon_key = serializers.CharField(source="beacon.key", read_only=True)
    beacon_title = serializers.CharField(source="beacon.title", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = FeedbackItem
        fields = (
            "id",
            "beacon_key",
            "beacon_title",
            "kind",
            "message",
            "page_url",
            "status",
            "created_at",
            "user_username",
        )
