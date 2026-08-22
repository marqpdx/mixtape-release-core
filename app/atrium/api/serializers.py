# atrium/api/serializers.py

from rest_framework import serializers

from atrium.models import AtriumSession, AtriumSessionEntry


class AtriumSessionEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AtriumSessionEntry
        fields = ["id", "role", "content", "created_at"]


class AtriumSessionListSerializer(serializers.ModelSerializer):
    entry_count = serializers.IntegerField(read_only=True)
    group_slug = serializers.SerializerMethodField()

    def get_group_slug(self, obj):
        return obj.group.slug if obj.group_id else None

    class Meta:
        model = AtriumSession
        fields = [
            "id",
            "title",
            "session_context",
            "dial_mode",
            "group_slug",
            "status",
            "last_activity_at",
            "entry_count",
            "created_at",
            "updated_at",
        ]
