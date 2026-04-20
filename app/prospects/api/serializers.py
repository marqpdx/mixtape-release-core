from rest_framework import serializers

from ..models import BusinessProspect, ProspectInsight, ProspectIntakeSession, ProspectNote, ProspectQuestion, ProspectResponse


class ProspectQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProspectQuestion
        fields = ["id", "prompt", "help_text", "order_index", "question_kind"]


class ProspectResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProspectResponse
        fields = ["id", "question_id", "question_prompt_snapshot", "response_text", "response_mode"]


class ProspectIntakeSessionSerializer(serializers.ModelSerializer):
    questions = serializers.SerializerMethodField()

    class Meta:
        model = ProspectIntakeSession
        fields = ["id", "mode", "status", "meeting_date", "questions"]

    def get_questions(self, obj):
        questions = ProspectQuestion.objects.filter(is_active=True).order_by("order_index")
        return ProspectQuestionSerializer(questions, many=True).data


class BusinessProspectSerializer(serializers.ModelSerializer):
    sponsor_group_slug = serializers.SerializerMethodField()

    class Meta:
        model = BusinessProspect
        fields = [
            "id", "name", "slug", "business_type", "website",
            "primary_contact_name", "primary_contact_email", "primary_contact_phone",
            "status", "summary", "sponsor_group_slug", "created_at",
        ]
        read_only_fields = ["id", "slug", "sponsor_group_slug", "created_at"]

    def get_sponsor_group_slug(self, obj):
        if obj.sponsor_content_type and obj.sponsor_content_type.model == "group":
            from groups.models import Group
            try:
                return Group.objects.get(pk=obj.sponsor_object_id).slug
            except Group.DoesNotExist:
                return None
        return None


class ProspectIntakeSessionInternalSerializer(serializers.ModelSerializer):
    responses = ProspectResponseSerializer(many=True, read_only=True)

    class Meta:
        model = ProspectIntakeSession
        fields = [
            "id", "mode", "status", "access_mode", "resume_token",
            "token_expires_at", "notify_on_submit", "started_at", "submitted_at",
            "reviewed_at", "meeting_date", "created_at", "responses",
        ]


class ProspectInsightSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProspectInsight
        fields = ["id", "source", "kind", "title", "body", "confidence", "created_at"]
        read_only_fields = ["id", "source", "created_at"]


class ProspectNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProspectNote
        fields = ["id", "body", "created_at"]
        read_only_fields = ["id", "created_at"]
