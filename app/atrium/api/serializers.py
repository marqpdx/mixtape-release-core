# atrium/api/serializers.py

from rest_framework import serializers

from atrium.models import AtriumSession, AtriumSessionEntry


class AtriumSessionEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AtriumSessionEntry
        fields = ["id", "role", "content", "created_at"]


class AtriumSessionListSerializer(serializers.ModelSerializer):
    entry_count = serializers.IntegerField(read_only=True)
    sponsor_type = serializers.SerializerMethodField()
    sponsor_slug = serializers.SerializerMethodField()
    initiative_title = serializers.SerializerMethodField()

    def get_sponsor_type(self, obj):
        if obj.sponsor_content_type_id:
            return obj.sponsor_content_type.model
        return None

    def get_sponsor_slug(self, obj):
        if obj.sponsor_object_id and obj.sponsor:
            return getattr(obj.sponsor, "slug", None)
        return None

    def get_initiative_title(self, obj):
        if obj.initiative_id:
            return getattr(obj.initiative, "title", None)
        return None

    class Meta:
        model = AtriumSession
        fields = [
            "id",
            "title",
            "session_context",
            "dial_mode",
            "sponsor_type",
            "sponsor_slug",
            "initiative_id",
            "initiative_title",
            "status",
            "last_activity_at",
            "entry_count",
            "created_at",
            "updated_at",
        ]
