from rest_framework import serializers

from ariadne.models import (
    Concept,
    ConceptAlias,
    CurationDecision,
    DiscoveryRun,
    EvidencePacket,
    Inquiry,
    InquiryReview,
    InquiryRun,
    InquiryTheme,
    RunCandidate,
)


class DiscoveryRunSerializer(serializers.ModelSerializer):
    lens_name = serializers.CharField(source="lens_version.lens.name", read_only=True)
    lens_version = serializers.IntegerField(source="lens_version.version", read_only=True)
    corpus_snapshot_captured_at = serializers.DateTimeField(source="corpus_snapshot.captured_at", read_only=True)
    candidate_count = serializers.SerializerMethodField()

    class Meta:
        model = DiscoveryRun
        fields = [
            "id", "status", "lens_name", "lens_version", "corpus_snapshot_captured_at",
            "target_concept_count", "started_at", "completed_at", "candidate_count",
        ]

    def get_candidate_count(self, run):
        return run.candidates.count()


class RunCandidateSerializer(serializers.ModelSerializer):
    concept_id = serializers.UUIDField(source="concept.id", read_only=True, default=None)
    concept_label = serializers.CharField(source="concept.preferred_label", read_only=True, default="")

    class Meta:
        model = RunCandidate
        fields = [
            "id", "concept_or_phrase_key", "rank", "score", "score_components", "summary",
            "disposition", "disposition_reason", "disposition_at", "concept_id", "concept_label",
        ]


class CurationDecisionInputSerializer(serializers.Serializer):
    candidate_key = serializers.CharField(max_length=256)
    action = serializers.ChoiceField(choices=CurationDecision.Action.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class EvidencePacketSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidencePacket
        fields = [
            "id", "run_id", "inquiry_run_id", "candidate_key", "subject_kind", "packet_version",
            "summary", "status", "created_at",
        ]


class EvidencePacketDetailSerializer(EvidencePacketSerializer):
    passages = serializers.SerializerMethodField()

    class Meta(EvidencePacketSerializer.Meta):
        fields = EvidencePacketSerializer.Meta.fields + ["passages"]

    def get_passages(self, packet):
        return self.context.get("passages", [])


class PacketAssembleInputSerializer(serializers.Serializer):
    candidate_key = serializers.CharField(max_length=256)


class SavedSearchInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=256)
    query = serializers.CharField(max_length=512)


class ConceptAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConceptAlias
        fields = ["alias", "alias_type", "language"]


class ConceptDetailSerializer(serializers.ModelSerializer):
    aliases = ConceptAliasSerializer(many=True, read_only=True)
    evidence = serializers.SerializerMethodField()

    class Meta:
        model = Concept
        fields = ["id", "preferred_label", "description", "status", "aliases", "evidence"]

    def get_evidence(self, concept):
        # P6a (build spec §19.6): "with its evidence" -- ConceptAssertion/
        # AssertionEvidence aren't populated by anything yet (§9 4E/4F, not
        # built this pass), so this is honestly empty today, not stubbed.
        return [
            {
                "assertion_id": str(assertion.id),
                "predicate": assertion.predicate,
                "object_concept_label": assertion.object_concept.preferred_label if assertion.object_concept else None,
                "claim_text": assertion.claim_text,
                "status": assertion.status,
            }
            for assertion in concept.subject_assertions.all()
        ]


# ---------------------------------------------------------------------------
# P9/P9a -- Inquiry Runs and the Review artifact (build spec §19.2-19.3)
# ---------------------------------------------------------------------------

class InquirySerializer(serializers.ModelSerializer):
    standing_review_id = serializers.UUIDField(source="standing_review.id", read_only=True, default=None)

    class Meta:
        model = Inquiry
        fields = ["id", "question", "sub_questions", "status", "standing_review_id", "created_at"]


class InquiryCreateInputSerializer(serializers.Serializer):
    question = serializers.CharField()


class FrameInputSerializer(serializers.Serializer):
    sub_questions = serializers.ListField(
        child=serializers.DictField(), required=False, allow_null=True, default=None,
    )
    use_model = serializers.BooleanField(default=False)


class ApproveSubQuestionsInputSerializer(serializers.Serializer):
    approved_texts = serializers.ListField(child=serializers.CharField())


class InquiryRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryRun
        fields = [
            "id", "inquiry_id", "status", "gathered_passage_ids", "model_versions",
            "started_at", "completed_at", "created_at",
        ]


class InquiryThemeSerializer(serializers.ModelSerializer):
    passage_count = serializers.SerializerMethodField()

    class Meta:
        model = InquiryTheme
        fields = ["id", "run_id", "label", "label_source", "passage_ids", "passage_count", "rank"]

    def get_passage_count(self, theme):
        return len(theme.passage_ids)


class LabelThemeInputSerializer(serializers.Serializer):
    use_model = serializers.BooleanField(default=False)


class DraftReviewInputSerializer(serializers.Serializer):
    use_model = serializers.BooleanField(default=False)
    cloud_approved = serializers.BooleanField(default=False)


class InquiryReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryReview
        fields = [
            "id", "inquiry_id", "run_id", "version", "body_markdown", "citations",
            "uncited_claim_count", "status", "superseded_review_id", "draft_calls", "created_at",
        ]


class CurateCitationInputSerializer(serializers.Serializer):
    citation_id = serializers.CharField()
    action = serializers.ChoiceField(choices=["accept", "amend", "strike"])
    amended_text = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)
