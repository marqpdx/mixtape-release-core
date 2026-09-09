from rest_framework import serializers

from sourcework.models import (
    ExternalConnection,
    ProvisionalData,
    ProvisionalDataMembership,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
)


class ExternalConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalConnection
        fields = [
            "id",
            "provider",
            "provider_account_id",
            "display_name",
            "provider_scopes",
            "status",
            "connected_at",
            "refreshed_at",
            "revoked_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "connected_at", "refreshed_at", "revoked_at", "created_at", "updated_at"]


class GmailLabelSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    type = serializers.CharField(required=False, allow_blank=True)


class SourceGrantSerializer(serializers.ModelSerializer):
    connection_display_name = serializers.CharField(source="connection.display_name", read_only=True)

    class Meta:
        model = SourceGrant
        fields = [
            "id",
            "connection",
            "connection_display_name",
            "initiative",
            "resource_kind",
            "resource_id",
            "display_name",
            "capabilities",
            "status",
            "revoked_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "revoked_at", "created_at", "updated_at"]


class SourceEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceEvidence
        fields = [
            "id",
            "provider_message_id",
            "provider_thread_id",
            "sender_email",
            "sender_display_name_raw",
            "sender_header_raw",
            "sent_at",
            "subject",
            "body_snapshot_status",
            "bounded_excerpt",
            "metadata",
            "ingested_at",
        ]


class RecruiterContactSerializer(serializers.ModelSerializer):
    """
    Serializer for ProvisionalData records of kind=recruiter_contact.
    Surfaces normalized_payload fields as top-level keys for frontend compat.
    """
    preferred_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    organization_guess = serializers.SerializerMethodField()
    name_source = serializers.SerializerMethodField()
    name_confidence = serializers.SerializerMethodField()
    name_status = serializers.SerializerMethodField()
    source_evidence = SourceEvidenceSerializer(read_only=True)

    class Meta:
        model = ProvisionalData
        fields = [
            "id",
            "kind",
            "state",
            "preferred_name",
            "email",
            "organization_guess",
            "name_source",
            "name_confidence",
            "name_status",
            "source_evidence",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "kind", "created_at", "updated_at"]

    def get_preferred_name(self, obj):
        return (obj.normalized_payload or {}).get("preferred_name", "")

    def get_email(self, obj):
        return (obj.normalized_payload or {}).get("email", "")

    def get_organization_guess(self, obj):
        return (obj.normalized_payload or {}).get("organization_guess", "")

    def get_name_source(self, obj):
        return (obj.normalized_payload or {}).get("name_source", "unknown")

    def get_name_confidence(self, obj):
        return (obj.normalized_payload or {}).get("name_confidence", "low")

    def get_name_status(self, obj):
        return (obj.normalized_payload or {}).get("name_status", "needs_review")


class WorkingSetMembershipSerializer(serializers.ModelSerializer):
    provisional_data = RecruiterContactSerializer(read_only=True)

    class Meta:
        model = ProvisionalDataMembership
        fields = ["id", "status", "position", "note", "provisional_data", "created_at", "updated_at"]


class WorkingSetSerializer(serializers.ModelSerializer):
    memberships = WorkingSetMembershipSerializer(
        source="provisional_data_memberships", many=True, read_only=True
    )

    class Meta:
        model = WorkingSet
        fields = [
            "id",
            "title",
            "purpose",
            "status",
            "summary",
            "initiative",
            "memberships",
            "created_at",
            "updated_at",
        ]


class LatestMessageSerializer(serializers.Serializer):
    provider_message_id = serializers.CharField(required=False, allow_blank=True)
    provider_thread_id = serializers.CharField(required=False, allow_blank=True)
    from_header = serializers.CharField(required=False, allow_blank=True)
    sender_header = serializers.CharField(required=False, allow_blank=True)
    sender_display_name = serializers.CharField(required=False, allow_blank=True)
    sender_email = serializers.EmailField(required=False, allow_blank=True)
    sent_at = serializers.CharField(required=False, allow_blank=True)
    date = serializers.CharField(required=False, allow_blank=True)
    subject = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)


class ImportLatestSerializer(serializers.Serializer):
    messages = LatestMessageSerializer(many=True)

    def validate_messages(self, value):
        if not value:
            raise serializers.ValidationError("At least one message is required for the V1 manual adapter.")
        return value[:5]


class ImportFromSourceSerializer(serializers.Serializer):
    adapter = serializers.ChoiceField(choices=["switchboard_gmail_v1"], default="switchboard_gmail_v1")
    limit = serializers.IntegerField(default=5, min_value=1, max_value=25)


class VerifyNameSerializer(serializers.Serializer):
    preferred_name = serializers.CharField(max_length=255)
    note = serializers.CharField(required=False, allow_blank=True)
