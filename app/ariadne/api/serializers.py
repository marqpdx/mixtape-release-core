from rest_framework import serializers

from ariadne.models import Concept, ConceptAlias, CurationDecision, DiscoveryRun, EvidencePacket, RunCandidate


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
            "id", "run_id", "candidate_key", "subject_kind", "packet_version",
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
