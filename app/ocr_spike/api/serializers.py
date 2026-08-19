from __future__ import annotations

import mimetypes

from rest_framework import serializers

from ocr_spike.models import (
    OcrSpikeArtifact,
    OcrSpikeEvaluation,
    OcrSpikeFeedbackNote,
    OcrSpikePage,
    OcrSpikeRecognitionAttempt,
)


class OcrSpikeRecognitionAttemptSerializer(serializers.ModelSerializer):
    attempt_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = OcrSpikeRecognitionAttempt
        fields = [
            "attempt_id",
            "provider",
            "engine_name",
            "raw_text",
            "confidence_summary",
            "processing_time_ms",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        ]


class OcrSpikeEvaluationSerializer(serializers.ModelSerializer):
    evaluation_id = serializers.UUIDField(source="id", read_only=True)
    selected_attempt_id = serializers.UUIDField(source="selected_attempt.id", read_only=True)

    class Meta:
        model = OcrSpikeEvaluation
        fields = [
            "evaluation_id",
            "selected_attempt_id",
            "final_text",
            "outcome",
            "quality_rating",
            "correction_effort",
            "search_summary",
            "notes",
            "created_at",
            "updated_at",
        ]


class OcrSpikePageSerializer(serializers.ModelSerializer):
    page_id = serializers.UUIDField(source="id", read_only=True)
    image_url = serializers.SerializerMethodField()
    image_content_type = serializers.SerializerMethodField()
    attempts = OcrSpikeRecognitionAttemptSerializer(many=True, read_only=True)
    evaluation = OcrSpikeEvaluationSerializer(read_only=True)

    class Meta:
        model = OcrSpikePage
        fields = [
            "page_id",
            "page_number",
            "image_url",
            "image_content_type",
            "width",
            "height",
            "preparation_status",
            "attempts",
            "evaluation",
        ]

    def get_image_url(self, page: OcrSpikePage) -> str:
        request = self.context.get("request")
        path = f"/api/spikes/ocr/pages/{page.id}/file/"
        return request.build_absolute_uri(path) if request else path

    def get_image_content_type(self, page: OcrSpikePage) -> str:
        if page.image_path:
            guessed = mimetypes.guess_type(page.image_path)[0]
            if guessed:
                return guessed
        return page.artifact.content_type or "application/octet-stream"


class OcrSpikeArtifactSerializer(serializers.ModelSerializer):
    artifact_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = OcrSpikeArtifact
        fields = [
            "artifact_id",
            "original_filename",
            "content_type",
            "file_size",
            "page_count",
            "privacy_sensitivity",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        ]


class OcrSpikeEvaluationWriteSerializer(serializers.Serializer):
    selected_attempt_id = serializers.UUIDField(required=False, allow_null=True)
    final_text = serializers.CharField(required=False, allow_blank=True)
    outcome = serializers.ChoiceField(choices=OcrSpikeEvaluation.Outcome.choices)
    quality_rating = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)
    correction_effort = serializers.ChoiceField(
        choices=OcrSpikeEvaluation.CorrectionEffort.choices,
        required=False,
        allow_blank=True,
    )
    search_summary = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class OcrSpikeFeedbackWriteSerializer(serializers.Serializer):
    artifact_id = serializers.UUIDField(required=False, allow_null=True)
    page_id = serializers.UUIDField(required=False, allow_null=True)
    screen = serializers.ChoiceField(choices=OcrSpikeFeedbackNote.Screen.choices)
    note = serializers.CharField()
