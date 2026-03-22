# initiatives/api/serializers.py

from rest_framework import serializers

from initiatives.models import Artifact, Initiative, LinkedOutput, Session


class InitiativeSerializer(serializers.ModelSerializer):
    rolling_summary = serializers.SerializerMethodField()
    last_session_at = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    thread_count = serializers.SerializerMethodField()

    class Meta:
        model = Initiative
        fields = [
            "id",
            "title",
            "direction",
            "status",
            "rolling_summary",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "parent",
            "thread_label",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "last_session_at",
            "thread_count",
        ]
        read_only_fields = [
            "id",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_rolling_summary(self, obj):
        return obj.rolling_summary_display

    def get_last_session_at(self, obj):
        dt = obj.last_session_at()
        return dt.isoformat() if dt else None

    def get_created_by_username(self, obj):
        return obj.created_by.username if obj.created_by else None

    def get_thread_count(self, obj):
        return obj.threads.count()


class SessionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.SerializerMethodField()
    artifact_count = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "id",
            "initiative",
            "intent",
            "capture_mode",
            "raw_transcript",
            "distillation",
            "distillation_state",
            "created_by",
            "created_by_username",
            "started_at",
            "ended_at",
            "created_at",
            "updated_at",
            "artifact_count",
        ]
        read_only_fields = [
            "id",
            "raw_transcript",
            "distillation_state",
            "created_by",
            "started_at",
            "created_at",
            "updated_at",
        ]

    def get_created_by_username(self, obj):
        return obj.created_by.username if obj.created_by else None

    def get_artifact_count(self, obj):
        return obj.artifacts.count()


class ArtifactSerializer(serializers.ModelSerializer):
    is_direct_annotation = serializers.BooleanField(read_only=True)

    class Meta:
        model = Artifact
        fields = [
            "id",
            "initiative",
            "session",
            "kind",
            "title",
            "body",
            "note",
            "quality_scan_result",
            "quality_scan_state",
            "puddlejump_routed",
            "puddlejump_routed_at",
            "is_direct_annotation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "quality_scan_result",
            "quality_scan_state",
            "puddlejump_routed",
            "puddlejump_routed_at",
            "created_at",
            "updated_at",
        ]


class LinkedOutputSerializer(serializers.ModelSerializer):
    output_type = serializers.SerializerMethodField()

    class Meta:
        model = LinkedOutput
        fields = [
            "id",
            "initiative",
            "output_content_type",
            "output_object_id",
            "output_type",
            "note",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_output_type(self, obj):
        return obj.output_content_type.model if obj.output_content_type else None


class RollingSummaryUpdateSerializer(serializers.Serializer):
    """For PATCH on rolling_summary — user edits one or more fields."""
    current_direction = serializers.CharField(required=False, allow_blank=True)
    key_decisions = serializers.ListField(child=serializers.CharField(), required=False)
    open_questions = serializers.ListField(child=serializers.CharField(), required=False)
    where_we_are_now = serializers.CharField(required=False, allow_blank=True)


class DistillationCurateSerializer(serializers.Serializer):
    """For commit-distillation — user's curated version of the AI proposal."""
    decisions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    open_questions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    actions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
