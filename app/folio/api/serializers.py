# folio/api/serializers.py

from rest_framework import serializers

from folio.models import Folio, FolioInception, FolioMaterialCandidate, FolioNote
from folio.shapes import Shape


class FolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Folio
        fields = ["id", "title", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class FolioMaterialCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FolioMaterialCandidate
        fields = [
            "id",
            "candidate_type",
            "ordinal",
            "source_span_start",
            "source_span_end",
            "source_text",
            "display_text",
            "confidence",
            "reason_code",
            "status",
            "parent_candidate",
            "created_at",
        ]
        read_only_fields = fields


class FolioInceptionSerializer(serializers.ModelSerializer):
    folio = FolioSerializer(read_only=True)
    material_candidates = FolioMaterialCandidateSerializer(many=True, read_only=True)

    class Meta:
        model = FolioInception
        fields = [
            "id",
            "folio",
            "raw_text",
            "pipeline_version",
            "model_id",
            "material_candidates",
            "created_at",
        ]
        read_only_fields = ["id", "folio", "pipeline_version", "model_id", "material_candidates", "created_at"]


class FolioInceptionCreateSerializer(serializers.Serializer):
    raw_text = serializers.CharField(allow_blank=False, trim_whitespace=False)
    title = serializers.CharField(required=False, allow_blank=True, default="")


class FolioTitlePatchSerializer(serializers.Serializer):
    title = serializers.CharField(allow_blank=True, trim_whitespace=False)


class FolioMaterialCandidatePatchSerializer(serializers.Serializer):
    # Only display_text is writable by a human. source_text/spans are the
    # verbatim record of what Hildegard found and stay immutable -- prototype
    # spec section 6, "Edits to the visible interpretation must not mutate
    # the raw inception."
    display_text = serializers.CharField(allow_blank=False, trim_whitespace=False)


class FolioCreateSerializer(serializers.Serializer):
    title = serializers.CharField(allow_blank=True, required=False, default="", max_length=255)


class FolioNoteSerializer(serializers.ModelSerializer):
    # `text` and `shape` are the resolved projections the capture surface
    # shows; the underlying raw/transcript and suggested/confirmed fields
    # stay exposed for provenance (build plan §38).
    text = serializers.CharField(read_only=True)
    shape = serializers.CharField(read_only=True)
    has_audio = serializers.SerializerMethodField()

    class Meta:
        model = FolioNote
        fields = [
            "id",
            "folio",
            "source_type",
            "status",
            "text",
            "raw_text",
            "transcript_text",
            "transcript_error",
            "has_audio",
            "shape",
            "suggested_shape",
            "shape_confidence",
            "confirmed_shape",
            "summary",
            "mentions",
            "tended_at",
            "tending_model",
            "tending_prompt_version",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_audio(self, obj):
        return obj.audio_file_id is not None


class FolioNotePatchSerializer(serializers.Serializer):
    # confirmed_shape: the writer's own choice (build plan §4.6). Blank clears
    # it, falling back to the model's suggestion; suggested_shape is never
    # writable here. folio: move the note to another of the writer's Folios
    # (Workbench light rearrangement, §55). At least one is required.
    confirmed_shape = serializers.ChoiceField(choices=Shape.choices, allow_blank=True, required=False)
    folio = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide confirmed_shape and/or folio.")
        return attrs


FolioNoteShapePatchSerializer = FolioNotePatchSerializer


class FolioNoteMentionConfirmSerializer(serializers.Serializer):
    # Link a tended mention to an existing Entity, or name a new one.
    entity_id = serializers.UUIDField(required=False)
    name = serializers.CharField(required=False, allow_blank=False, max_length=255)
    kind = serializers.ChoiceField(choices=["character", "setting", "thing", "concept"], required=False)

    def validate(self, attrs):
        if not attrs.get("entity_id") and not (attrs.get("name") or "").strip():
            raise serializers.ValidationError("Choose an existing Entity or name a new one.")
        return attrs


class FolioNoteTextCreateSerializer(serializers.Serializer):
    raw_text = serializers.CharField(allow_blank=False, trim_whitespace=False)
    source = serializers.CharField(required=False, allow_blank=True, default="", max_length=32)
