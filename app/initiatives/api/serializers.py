# initiatives/api/serializers.py

import datetime

from django.utils import timezone
from rest_framework import serializers

from initiatives.models import (
    ActionRun,
    ActionRunStatus,
    Artifact,
    ApertureLog,
    ApertureLogEntry,
    ApertureLogEntryKind,
    DistillationState,
    Initiative,
    LinkedOutput,
    Session,
)

_MOMENTUM_WINDOW_DAYS = 14


class InitiativeSerializer(serializers.ModelSerializer):
    rolling_summary = serializers.SerializerMethodField()
    last_session_at = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    thread_count = serializers.SerializerMethodField()
    momentum_score = serializers.SerializerMethodField()

    class Meta:
        model = Initiative
        fields = [
            "id",
            "title",
            "direction",
            "status",
            "status_note",
            "rolling_summary",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "thread_summaries",
            "seeded_from",
            "parent",
            "thread_label",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "last_session_at",
            "thread_count",
            "momentum_score",
        ]
        read_only_fields = [
            "id",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "thread_summaries",
            "seeded_from",
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

    def get_momentum_score(self, obj):
        """
        Momentum = Mass × Velocity

        Mass  — total accumulated material (sessions + distillation items + artifacts + linked outputs)
        Velocity — new material in the trailing 14-day window

        Uses prefetched sessions when available (list view); falls back to
        DB queries (detail view). Artifacts and linked outputs always query
        the DB — add prefetch_related("artifacts", "linked_outputs") to the
        list queryset when scale requires it.
        """
        cutoff = timezone.now() - datetime.timedelta(days=_MOMENTUM_WINDOW_DAYS)

        # Sessions — use prefetch cache if present to avoid N+1
        sessions = list(obj.sessions.all())
        session_count = len(sessions)

        distillation_items = sum(
            len(s.distillation.get("decisions", [])) +
            len(s.distillation.get("open_questions", [])) +
            len(s.distillation.get("actions", []))
            for s in sessions
            if s.distillation_state == DistillationState.CURATED and s.distillation
        )

        artifact_count = obj.artifacts.count()
        linked_output_count = obj.linked_outputs.count()

        mass = session_count + distillation_items + artifact_count + linked_output_count

        recent_sessions = sum(1 for s in sessions if s.started_at >= cutoff)
        recent_artifacts = obj.artifacts.filter(created_at__gte=cutoff).count()
        velocity = recent_sessions + recent_artifacts

        if mass == 0 or velocity == 0:
            return 0.0
        return round(float(mass * velocity), 2)


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
            "initiative",
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


class ApertureLogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ApertureLogEntry
        fields = [
            "id",
            "aperture_log",
            "kind",
            "body",
            "emph_note",
            "ledger_event_type",
            "ledger_data",
            "spawned_seed_content_type",
            "spawned_seed_object_id",
            "emph_is_summary_candidate",
            "emph_accepted_to_summary",
            "is_system_generated",
            "authored_by",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "aperture_log",
            "ledger_event_type",
            "ledger_data",
            "spawned_seed_content_type",
            "spawned_seed_object_id",
            "emph_is_summary_candidate",
            "is_system_generated",
            "authored_by",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_kind(self, value):
        if value in (ApertureLogEntryKind.LEDGER, ApertureLogEntryKind.SEED_SPAWN, ApertureLogEntryKind.RUN_BOUNDARY):
            raise serializers.ValidationError("Ledger, seed_spawn, and run_boundary entries are system-generated only.")
        return value


class ApertureLogSerializer(serializers.ModelSerializer):
    entries = ApertureLogEntrySerializer(many=True, read_only=True)

    class Meta:
        model = ApertureLog
        fields = ["id", "initiative", "last_handoff_at", "created_at", "updated_at", "entries"]
        read_only_fields = ["id", "initiative", "last_handoff_at", "created_at", "updated_at"]


class ActionRunCreateSerializer(serializers.ModelSerializer):
    initiative_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    session_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    parent_action_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = ActionRun
        fields = [
            "id",
            "initiative_id",
            "session_id",
            "tool_name",
            "execution_mode",
            "service_name",
            "tenant_id",
            "tenant_namespace",
            "initiator_type",
            "initiator_id",
            "parent_action_id",
            "request_payload",
            "cloud_approved",
            "approval_payload",
            "status",
            "started_at",
            "completed_at",
        ]
        read_only_fields = ["id", "status", "started_at", "completed_at"]

    def validate(self, attrs):
        initiative_id = attrs.pop("initiative_id", None)
        session_id = attrs.pop("session_id", None)
        parent_action_id = attrs.pop("parent_action_id", None)

        if initiative_id:
            try:
                attrs["initiative"] = Initiative.objects.get(pk=initiative_id)
            except Initiative.DoesNotExist as exc:
                raise serializers.ValidationError({"initiative_id": "Initiative not found."}) from exc

        if session_id:
            try:
                attrs["session"] = Session.objects.get(pk=session_id)
            except Session.DoesNotExist as exc:
                raise serializers.ValidationError({"session_id": "Session not found."}) from exc

        if parent_action_id:
            try:
                attrs["parent_action"] = ActionRun.objects.get(pk=parent_action_id)
            except ActionRun.DoesNotExist as exc:
                raise serializers.ValidationError({"parent_action_id": "Parent action not found."}) from exc

        session = attrs.get("session")
        initiative = attrs.get("initiative")
        if session and initiative and session.initiative_id != initiative.id:
            raise serializers.ValidationError({"session_id": "Session does not belong to initiative."})

        if session and not initiative:
            attrs["initiative"] = session.initiative

        return attrs


class ActionRunPatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionRun
        fields = [
            "status",
            "result_payload",
            "error_payload",
            "completed_at",
        ]

    def validate_status(self, value):
        if value not in {ActionRunStatus.SUCCEEDED, ActionRunStatus.FAILED}:
            raise serializers.ValidationError("Status must transition to succeeded or failed.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance.status != ActionRunStatus.PENDING:
            raise serializers.ValidationError("Only pending runs may be finalized.")

        status_value = attrs.get("status")
        if status_value == ActionRunStatus.SUCCEEDED and "error_payload" in attrs and attrs["error_payload"]:
            raise serializers.ValidationError({"error_payload": "Successful runs cannot include error payload."})
        if status_value == ActionRunStatus.FAILED and not attrs.get("error_payload"):
            raise serializers.ValidationError({"error_payload": "Failed runs require error payload."})

        return attrs

    def update(self, instance, validated_data):
        instance.status = validated_data["status"]
        instance.result_payload = validated_data.get("result_payload")
        instance.error_payload = validated_data.get("error_payload")
        instance.completed_at = validated_data.get("completed_at") or timezone.now()
        instance.save(update_fields=["status", "result_payload", "error_payload", "completed_at", "updated_at"])
        return instance


class ActionRunSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionRun
        fields = ["id", "status", "started_at", "completed_at"]


class DistillationCurateSerializer(serializers.Serializer):
    """For commit-distillation — user's curated version of the AI proposal."""
    decisions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    open_questions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    actions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
