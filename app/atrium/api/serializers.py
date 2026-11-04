# atrium/api/serializers.py

from rest_framework import serializers

from atrium.models import Dialogue, DialogueEntry, Distillate


class DialogueEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = DialogueEntry
        fields = [
            "id",
            "role",
            "speaker",
            "content",
            "entry_type",
            "document_title",
            "status",
            "error_code",
            "created_at",
        ]


class DialogueListSerializer(serializers.ModelSerializer):
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
        model = Dialogue
        fields = [
            "id",
            "title",
            "session_context",
            "dial_mode",
            "ai_provider",
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


class DistillateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Distillate
        fields = ["id", "title", "body", "document_type", "status", "error_code", "created_at"]
