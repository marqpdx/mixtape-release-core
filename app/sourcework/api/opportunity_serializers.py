from rest_framework import serializers

from sourcework.models import (
    OpportunityApplicationDraft,
    OpportunityProfile,
    ProvisionalData,
    ProvisionalDataMembership,
    WorkingSet,
)


class OpportunityProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpportunityProfile
        fields = [
            "id",
            "version",
            "is_current",
            "name",
            "resume_label",
            "resume_version",
            "query_lanes",
            "target_roles",
            "geography",
            "workplace_types",
            "employment_types",
            "seniority",
            "strong_domains",
            "strong_technologies",
            "exclusions",
            "freshness_hours",
            "preferences",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "is_current", "created_at", "updated_at"]

    def validate_query_lanes(self, value):
        for index, lane in enumerate(value):
            if not isinstance(lane, dict) or not str(lane.get("keyword") or "").strip():
                raise serializers.ValidationError(f"Query lane {index + 1} needs a keyword.")
        return value

    def validate_freshness_hours(self, value):
        if value not in {24, 72, 168}:
            raise serializers.ValidationError("Freshness must be 24, 72, or 168 hours.")
        return value


class OpportunityCandidateSerializer(serializers.ModelSerializer):
    payload = serializers.JSONField(source="normalized_payload", read_only=True)
    source_url = serializers.CharField(source="source_locator", read_only=True)

    class Meta:
        model = ProvisionalData
        fields = [
            "id",
            "state",
            "confidence",
            "freshness",
            "source_type",
            "source_url",
            "payload",
            "observed_at",
            "captured_at",
            "created_at",
            "updated_at",
        ]


class OpportunityMembershipSerializer(serializers.ModelSerializer):
    opportunity = OpportunityCandidateSerializer(source="provisional_data", read_only=True)

    class Meta:
        model = ProvisionalDataMembership
        fields = ["id", "position", "status", "note", "opportunity"]


class OpportunityWorkingSetSerializer(serializers.ModelSerializer):
    opportunities = OpportunityMembershipSerializer(
        source="provisional_data_memberships",
        many=True,
        read_only=True,
    )

    class Meta:
        model = WorkingSet
        fields = [
            "id",
            "title",
            "purpose",
            "status",
            "source",
            "search_brief",
            "execution_metadata",
            "summary",
            "opportunities",
            "created_at",
            "updated_at",
        ]


class OpportunityStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=["new", "reviewing", "interesting", "rejected"])


class OpportunityApplicationDraftSerializer(serializers.ModelSerializer):
    profile_version = serializers.IntegerField(source="profile.version", read_only=True)
    resume_label = serializers.CharField(source="profile.resume_label", read_only=True)
    resume_version = serializers.CharField(source="profile.resume_version", read_only=True)

    class Meta:
        model = OpportunityApplicationDraft
        fields = [
            "id",
            "status",
            "recipient_name",
            "recipient_email",
            "letter_body",
            "generation_context",
            "generated_by",
            "generated_at",
            "profile_version",
            "resume_label",
            "resume_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "generation_context",
            "generated_by",
            "generated_at",
            "profile_version",
            "resume_label",
            "resume_version",
            "created_at",
            "updated_at",
        ]
