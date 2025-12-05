from rest_framework import serializers

from ..models import BlacklistedTitle, LLMMessage, LLMSession, SuggestedAsset


class LLMMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMMessage
        fields = ["id", "role", "text", "markdown_text", "timestamp"]

class LLMSessionSerializer(serializers.ModelSerializer):
    messages = LLMMessageSerializer(many=True, read_only=True)

    class Meta:
        model = LLMSession
        fields = ["session_id", "created_at", "messages"]


class SuggestedAssetSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = SuggestedAsset
        fields = [
            "id", "title", "author", "source_url", "score", "approved", "cover_url",
            "retrieved", "synopsis", "synopsis_status", "source", "suggested_at",
            "status", "source_id", "asset_type", "subject_tags", "retrieved_at",
            "ingested", "ingestion_status"
        ]


class SuggestedAssetUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuggestedAsset
        fields = ["title", "author", "subject_tags", "score"]



class BlacklistedTitleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlacklistedTitle
        fields = ["id", "loose_title", "reason", "created_at"]
        read_only_fields = ["id", "created_at"]
