from rest_framework import serializers
from django.utils import timezone

from assets.models import Asset, ProfileAsset
from utils.writing.writing_utils import extract_text_from_prosemirror
from sourcework.models import (
    OpportunityApplicationDraft,
    OpportunityProfile,
    ProvisionalData,
    ProvisionalDataMembership,
    WorkingSet,
)


class OpportunityProfileSerializer(serializers.ModelSerializer):
    resume_asset = serializers.SerializerMethodField()
    resume_asset_id = serializers.PrimaryKeyRelatedField(
        source="resume_asset",
        queryset=Asset.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = OpportunityProfile
        fields = [
            "id",
            "version",
            "is_current",
            "name",
            "resume_label",
            "resume_version",
            "resume_asset",
            "resume_asset_id",
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

    def validate_resume_asset_id(self, asset):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            raise serializers.ValidationError("A signed-in member is required.")
        if not ProfileAsset.objects.filter(asset=asset, profile__user=request.user).exists():
            raise serializers.ValidationError("Select a document from your own profile assets.")
        if asset.type != "document" or asset.file_type != "application/pdf":
            raise serializers.ValidationError("The selected résumé must be a PDF document.")
        if asset.file_size and asset.file_size > 2 * 1024 * 1024:
            raise serializers.ValidationError("The selected résumé exceeds Dice's 2 MB limit.")
        return asset

    def get_resume_asset(self, obj):
        return serialize_resume_asset(obj.resume_asset)


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


class OpportunitySearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)


class OpportunityURLImportSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=1000)


class OpportunityApplicationDraftSerializer(serializers.ModelSerializer):
    profile_version = serializers.IntegerField(source="profile.version", read_only=True)
    resume_label = serializers.CharField(source="profile.resume_label", read_only=True)
    resume_version = serializers.CharField(source="profile.resume_version", read_only=True)
    resume_asset = serializers.SerializerMethodField()

    class Meta:
        model = OpportunityApplicationDraft
        fields = [
            "id",
            "status",
            "opportunity_title",
            "recipient_name",
            "recipient_email",
            "letter_body",
            "letter_body_json",
            "generation_context",
            "generated_by",
            "generated_at",
            "submitted_at",
            "profile_version",
            "resume_label",
            "resume_version",
            "resume_asset",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "generation_context",
            "generated_by",
            "generated_at",
            "submitted_at",
            "profile_version",
            "resume_label",
            "resume_version",
            "resume_asset",
            "created_at",
            "updated_at",
        ]

    def get_resume_asset(self, obj):
        return serialize_resume_asset(obj.resume_asset)

    def validate_letter_body_json(self, value):
        if value and (not isinstance(value, dict) or value.get("type") != "doc"):
            raise serializers.ValidationError("Cover-letter content must be a TipTap document.")
        return value

    def update(self, instance, validated_data):
        body_json = validated_data.get("letter_body_json")
        if body_json is not None:
            validated_data["letter_body"] = extract_text_from_prosemirror(body_json)
        next_status = validated_data.get("status")
        if next_status == "submitted" and instance.submitted_at is None:
            validated_data["submitted_at"] = timezone.now()
        elif next_status and next_status != "submitted" and instance.status == "submitted":
            validated_data["submitted_at"] = None
        return super().update(instance, validated_data)


def serialize_resume_asset(asset):
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "type": asset.type,
        "file_name": asset.file_name,
        "file_type": asset.file_type,
        "file_size": asset.file_size,
        "upload_status": asset.upload_status,
        "privacy": asset.privacy,
    }
