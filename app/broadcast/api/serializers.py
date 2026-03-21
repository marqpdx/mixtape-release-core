# broadcast/api/serializers.py
from rest_framework import serializers

from broadcast.models import (
    BroadcastAudience,
    BroadcastDelivery,
    GroupBroadcast,
    UserBroadcastPreferences,
)


class BroadcastAudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BroadcastAudience
        fields = ["scope_type", "role", "user_ids"]


class GroupBroadcastCreateSerializer(serializers.ModelSerializer):
    audience = BroadcastAudienceSerializer(write_only=True)

    class Meta:
        model = GroupBroadcast
        fields = ["title", "body", "priority", "channels", "scheduled_at", "audience"]

    def validate_channels(self, value):
        valid = {c.value for c in GroupBroadcast.Channel}
        bad = [c for c in value if c not in valid]
        if bad:
            raise serializers.ValidationError(f"Invalid channels: {bad}. Valid: {sorted(valid)}")
        if not value:
            raise serializers.ValidationError("At least one channel is required.")
        return value

    def validate(self, data):
        audience = data.get("audience", {})
        scope = audience.get("scope_type")
        if scope == "role" and not audience.get("role"):
            raise serializers.ValidationError({"audience": "role is required for scope_type='role'."})
        if scope == "custom" and not audience.get("user_ids"):
            raise serializers.ValidationError({"audience": "user_ids required for scope_type='custom'."})
        return data

    def create(self, validated_data):
        audience_data = validated_data.pop("audience")
        broadcast = GroupBroadcast.objects.create(**validated_data)
        BroadcastAudience.objects.create(broadcast=broadcast, **audience_data)
        return broadcast


class GroupBroadcastSerializer(serializers.ModelSerializer):
    audiences = BroadcastAudienceSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = GroupBroadcast
        fields = [
            "id", "title", "body", "priority", "channels", "status",
            "scheduled_at", "sent_at", "created_at", "created_by_username", "audiences",
        ]
        read_only_fields = ["id", "status", "sent_at", "created_at", "created_by_username"]


class BroadcastDeliverySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = BroadcastDelivery
        fields = ["id", "username", "channel", "status", "sent_at", "error_message"]


class UserBroadcastPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserBroadcastPreferences
        fields = ["id", "group", "allow_in_app", "allow_email", "allow_sms"]
        read_only_fields = ["id", "sms_verified"]
