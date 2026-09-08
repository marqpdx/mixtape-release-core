from rest_framework import serializers

from sourcework.models import (
    ExternalConnection,
    ProvisionalThing,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
    WorkingSetMembership,
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


class ProvisionalThingSerializer(serializers.ModelSerializer):
    evidence = SourceEvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = ProvisionalThing
        fields = [
            "id",
            "possible_type",
            "status",
            "preferred_name",
            "email",
            "organization_guess",
            "relationship_context",
            "name_source",
            "name_confidence",
            "name_status",
            "payload",
            "evidence",
            "verified_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "possible_type", "verified_at", "created_at", "updated_at"]


class WorkingSetMembershipSerializer(serializers.ModelSerializer):
    provisional_thing = ProvisionalThingSerializer(read_only=True)

    class Meta:
        model = WorkingSetMembership
        fields = ["id", "status", "position", "note", "provisional_thing", "created_at", "updated_at"]


class WorkingSetSerializer(serializers.ModelSerializer):
    memberships = WorkingSetMembershipSerializer(many=True, read_only=True)

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


class VerifyNameSerializer(serializers.Serializer):
    preferred_name = serializers.CharField(max_length=255)
    note = serializers.CharField(required=False, allow_blank=True)
