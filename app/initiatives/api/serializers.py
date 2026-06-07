# initiatives/api/serializers.py

import datetime

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import serializers

from initiatives.models import (
    AgentCommand,
    ActionRun,
    ActionRunStatus,
    Artifact,
    ApertureLog,
    ApertureLogEntry,
    ApertureLogEntryKind,
    CaptureMode,
    DistillationState,
    Initiative,
    InitiativeArtifact,
    Note,
    Reminder,
    Session,
    Task,
)
from initiatives.services import resolve_content_type_for_sponsor_model

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


class LinkedOutputCreateSerializer(serializers.Serializer):
    """Validation for linking an artifact to an Initiative."""

    output_content_type_id = serializers.IntegerField()
    output_object_id = serializers.UUIDField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


def serialize_linked_output(r):
    return {
        "id": str(r.id),
        "output_content_type": r.target_content_type_id,
        "output_object_id": str(r.target_object_id),
        "output_type": r.target_content_type.model if r.target_content_type else None,
        "note": r.notes,
        "created_at": r.created_at,
    }


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
        if value not in {
            ActionRunStatus.RUNNING,
            ActionRunStatus.SUCCEEDED,
            ActionRunStatus.FAILED,
        }:
            raise serializers.ValidationError("Status must transition to running, succeeded, or failed.")
        return value

    def validate(self, attrs):
        instance = self.instance
        status_value = attrs.get("status")
        allowed_transitions = {
            ActionRunStatus.PENDING: {
                ActionRunStatus.RUNNING,
                ActionRunStatus.SUCCEEDED,
                ActionRunStatus.FAILED,
            },
            ActionRunStatus.RUNNING: {
                ActionRunStatus.SUCCEEDED,
                ActionRunStatus.FAILED,
            },
        }
        if status_value not in allowed_transitions.get(instance.status, set()):
            raise serializers.ValidationError(
                f"ActionRun may not transition from {instance.status} to {status_value}."
            )

        if status_value == ActionRunStatus.RUNNING:
            if attrs.get("result_payload"):
                raise serializers.ValidationError({"result_payload": "Running runs cannot include result payload."})
            if attrs.get("error_payload"):
                raise serializers.ValidationError({"error_payload": "Running runs cannot include error payload."})
            if attrs.get("completed_at"):
                raise serializers.ValidationError({"completed_at": "Running runs cannot set completion time."})

        if status_value == ActionRunStatus.SUCCEEDED and "error_payload" in attrs and attrs["error_payload"]:
            raise serializers.ValidationError({"error_payload": "Successful runs cannot include error payload."})
        if status_value == ActionRunStatus.FAILED and not attrs.get("error_payload"):
            raise serializers.ValidationError({"error_payload": "Failed runs require error payload."})

        return attrs

    def update(self, instance, validated_data):
        instance.status = validated_data["status"]
        update_fields = ["status", "updated_at"]

        if "result_payload" in validated_data:
            instance.result_payload = validated_data.get("result_payload")
            update_fields.append("result_payload")
        if "error_payload" in validated_data:
            instance.error_payload = validated_data.get("error_payload")
            update_fields.append("error_payload")

        if validated_data["status"] == ActionRunStatus.RUNNING:
            instance.completed_at = None
            update_fields.append("completed_at")
        else:
            instance.completed_at = validated_data.get("completed_at") or timezone.now()
            update_fields.append("completed_at")

        instance.save(update_fields=update_fields)
        return instance


class ActionRunSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionRun
        fields = ["id", "status", "started_at", "completed_at"]


class ActionRunDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionRun
        fields = [
            "id",
            "tool_name",
            "status",
            "execution_mode",
            "service_name",
            "started_at",
            "completed_at",
            "result_payload",
            "error_payload",
        ]


class _AgentObjectSerializerMixin(serializers.ModelSerializer):
    initiative_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    sponsor_model = serializers.CharField(required=False, allow_blank=False, write_only=True)
    sponsor_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    def validate(self, attrs):
        initiative_id = attrs.pop("initiative_id", None)
        sponsor_model = attrs.pop("sponsor_model", None)
        sponsor_id = attrs.pop("sponsor_id", None)

        initiative = None
        if initiative_id:
            try:
                initiative = Initiative.objects.get(pk=initiative_id)
            except Initiative.DoesNotExist as exc:
                raise serializers.ValidationError({"initiative_id": "Initiative not found."}) from exc

        if initiative:
            attrs["initiative"] = initiative
            attrs["sponsor_content_type"] = initiative.sponsor_content_type
            attrs["sponsor_object_id"] = initiative.sponsor_object_id
        else:
            if not sponsor_model or not sponsor_id:
                raise serializers.ValidationError(
                    "Provide either initiative_id or both sponsor_model and sponsor_id."
                )
            try:
                content_type = resolve_content_type_for_sponsor_model(sponsor_model)
            except ContentType.DoesNotExist as exc:
                raise serializers.ValidationError({"sponsor_model": "Sponsor model not found."}) from exc

            model_class = content_type.model_class()
            if model_class is None:
                raise serializers.ValidationError({"sponsor_model": "Sponsor model is not concrete."})
            try:
                model_class.objects.get(pk=sponsor_id)
            except model_class.DoesNotExist as exc:
                raise serializers.ValidationError({"sponsor_id": "Sponsor object not found."}) from exc

            attrs["sponsor_content_type"] = content_type
            attrs["sponsor_object_id"] = sponsor_id

        return attrs


class NoteSerializer(_AgentObjectSerializerMixin):
    class Meta:
        model = Note
        fields = [
            "id",
            "initiative",
            "initiative_id",
            "sponsor_model",
            "sponsor_id",
            "title",
            "body",
            "capture_mode",
            "origin",
            "raw_input",
            "parsed_metadata",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "initiative", "created_by", "created_at", "updated_at"]


class ReminderSerializer(_AgentObjectSerializerMixin):
    class Meta:
        model = Reminder
        fields = [
            "id",
            "initiative",
            "initiative_id",
            "sponsor_model",
            "sponsor_id",
            "title",
            "body",
            "remind_at",
            "status",
            "snoozed_until",
            "capture_mode",
            "origin",
            "raw_input",
            "parsed_metadata",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "initiative", "status", "created_by", "created_at", "updated_at"]


class TaskSerializer(_AgentObjectSerializerMixin):
    assigned_to_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "initiative",
            "initiative_id",
            "sponsor_model",
            "sponsor_id",
            "title",
            "details",
            "status",
            "due_at",
            "assigned_to",
            "assigned_to_id",
            "capture_mode",
            "origin",
            "raw_input",
            "parsed_metadata",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "initiative", "created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        assigned_to_id = attrs.pop("assigned_to_id", None)
        if assigned_to_id:
            from django.contrib.auth import get_user_model

            user_model = get_user_model()
            try:
                attrs["assigned_to"] = user_model.objects.get(pk=assigned_to_id)
            except user_model.DoesNotExist as exc:
                raise serializers.ValidationError({"assigned_to_id": "Assigned user not found."}) from exc
        return attrs


class DistillationCurateSerializer(serializers.Serializer):
    """For commit-distillation — user's curated version of the AI proposal."""
    decisions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    open_questions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    actions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MobileCommandCreateSerializer(serializers.Serializer):
    text = serializers.CharField()
    source = serializers.CharField(required=False, default="mobile_initiatives")
    capture_mode = serializers.ChoiceField(choices=CaptureMode.choices, required=False, default=CaptureMode.TYPED)
    session_id = serializers.CharField(required=False, allow_blank=True, default="")
    draft_id = serializers.CharField(required=False, allow_blank=True, default="")
    initiative_id = serializers.UUIDField(required=False, allow_null=True)
    sponsor_model = serializers.CharField(required=False, allow_blank=False)
    sponsor_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("initiative_id") and not (attrs.get("sponsor_model") and attrs.get("sponsor_id")):
            raise serializers.ValidationError(
                "Provide either initiative_id or both sponsor_model and sponsor_id."
            )
        return attrs


class MobileCommandConfirmSerializer(serializers.Serializer):
    confirm_action = serializers.ChoiceField(choices=["confirm"])
    fields = serializers.JSONField(required=False, default=dict)


class AgentCommandDetailSerializer(serializers.ModelSerializer):
    command_id = serializers.UUIDField(source="id", read_only=True)
    verb = serializers.CharField(source="parsed_verb", read_only=True)
    executed_verb = serializers.CharField(read_only=True)
    title = serializers.CharField(source="parsed_title", read_only=True)
    summary = serializers.CharField(source="parsed_summary", read_only=True)
    fields = serializers.JSONField(source="parsed_fields", read_only=True)
    generated_text = serializers.CharField(read_only=True)
    needs_clarification = serializers.BooleanField(read_only=True)
    clarification_reason = serializers.CharField(read_only=True)
    result_payload = serializers.JSONField(read_only=True)
    follow_up_suggestions = serializers.JSONField(read_only=True)
    routing = serializers.JSONField(source="routing_metadata", read_only=True)

    class Meta:
        model = AgentCommand
        fields = [
            "id",
            "command_id",
            "status",
            "source",
            "capture_mode",
            "draft_session_id",
            "verb",
            "executed_verb",
            "confidence",
            "title",
            "summary",
            "fields",
            "generated_text",
            "needs_clarification",
            "clarification_reason",
            "result_type",
            "result_payload",
            "follow_up_suggestions",
            "routing",
            "error_payload",
            "created_at",
            "updated_at",
        ]


# ---------------------------------------------------------------------------
# Radar serializers (W-16)
# ---------------------------------------------------------------------------

class RadarInitiativeSerializer(serializers.ModelSerializer):
    last_session_at = serializers.SerializerMethodField()

    class Meta:
        model = Initiative
        fields = [
            "id",
            "title",
            "direction",
            "status",
            "is_personal",
            "narrative",
            "position",
            "last_session_note",
            "member_last_active_at",
            "created_at",
            "updated_at",
            "last_session_at",
        ]
        read_only_fields = ["id", "is_personal", "member_last_active_at", "created_at", "updated_at"]

    def get_last_session_at(self, obj):
        dt = obj.last_session_at()
        return dt.isoformat() if dt else None


class RadarInitiativeArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = InitiativeArtifact
        fields = [
            "id",
            "initiative",
            "artifact_type",
            "label",
            "doc_path",
            "conversation_source",
            "conversation_text",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "initiative",
            "artifact_type",
            "doc_path",
            "conversation_source",
            "conversation_text",
            "created_at",
            "updated_at",
        ]
