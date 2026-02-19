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

