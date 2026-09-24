# folio/api/serializers.py

from rest_framework import serializers

from folio.models import Folio, FolioInception, FolioMaterialCandidate


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
