# distribution/api/serializers.py

from rest_framework import serializers

from distribution.models import PublishEvent, ShareRecord, Source


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = [
            "id", "kind", "label", "tier_required",
            "config_schema", "is_active", "group",
        ]
        read_only_fields = fields


class ShareRecordSerializer(serializers.ModelSerializer):
    source_kind = serializers.CharField(source="source.kind", read_only=True)
    source_label = serializers.CharField(source="source.label", read_only=True)

    class Meta:
        model = ShareRecord
        fields = [
            "id", "source", "source_kind", "source_label",
            "canonical_url", "og_title", "synopsis", "og_image",
            "channel_config", "channel_response",
            "shared_at", "status", "failure_reason",
        ]
        read_only_fields = fields


class PublishEventSerializer(serializers.ModelSerializer):
    share_records = ShareRecordSerializer(many=True, read_only=True)

    class Meta:
        model = PublishEvent
        fields = [
            "id", "writing_piece", "status",
            "sources_config", "scheduled_at", "executed_at",
            "created_at", "share_records",
        ]
        read_only_fields = fields


class DistributeRequestSerializer(serializers.Serializer):
    """
    Payload for POST /distribute — list of source channel configs.
    """
    sources = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        allow_empty=False,
        help_text="[{source_id: uuid, config: {...}}, ...]",
    )
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
