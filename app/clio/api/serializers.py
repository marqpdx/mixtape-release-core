from rest_framework import serializers

from clio.models import KeeperClosingMode, KeeperFindingCadence, KeeperRegistration


class QuestionShapeSerializer(serializers.Serializer):
    intent = serializers.SlugField(max_length=200)
    description = serializers.CharField()
    answer_task = serializers.CharField(max_length=500)


class KeeperRegisterSerializer(serializers.Serializer):
    """
    Validates a registration payload against the AD-10 wire format exactly.
    """

    keeper_id = serializers.SlugField(max_length=200)
    keeper_name = serializers.CharField(max_length=200)
    owner_subsystem = serializers.CharField(max_length=200)
    watch_scope = serializers.CharField()
    question_shapes = QuestionShapeSerializer(many=True, required=False, default=list)
    finding_cadence = serializers.ChoiceField(choices=KeeperFindingCadence.choices)
    closing_mode = serializers.ChoiceField(choices=KeeperClosingMode.choices, default=KeeperClosingMode.ARCHIVE)
    instance_params = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        cadence = attrs.get("finding_cadence")
        question_shapes = attrs.get("question_shapes") or []
        if cadence in (KeeperFindingCadence.REACTIVE, KeeperFindingCadence.BOTH) and not question_shapes:
            raise serializers.ValidationError(
                "question_shapes is required when finding_cadence is 'reactive' or 'both' — "
                "a Keeper that answers questions must declare at least one question shape."
            )
        return attrs


class KeeperDeregisterSerializer(serializers.Serializer):
    closing_mode = serializers.ChoiceField(choices=KeeperClosingMode.choices, required=False)


class KeeperRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = KeeperRegistration
        fields = [
            "id",
            "keeper_id",
            "keeper_name",
            "owner_subsystem",
            "watch_scope",
            "question_shapes",
            "finding_cadence",
            "closing_mode",
            "instance_params",
            "status",
            "registered_at",
            "archived_at",
        ]
        read_only_fields = fields
