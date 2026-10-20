from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from shuttle.interpretation import lifecycle


class StartInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    seed_id = serializers.UUIDField()
    client = serializers.ChoiceField(choices=["phone", "desktop"], default="phone")


class ExecuteInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=0)
    source_digest = serializers.RegexField(r"^[a-f0-9]{64}$")
    cloud_consent = serializers.BooleanField(default=False)


class CorrectionInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=0)
    correction_text = serializers.CharField(required=False, max_length=12000, trim_whitespace=False)
    correction_seed_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if ("correction_text" in attrs) == ("correction_seed_id" in attrs):
            raise serializers.ValidationError("Supply exactly one correction source.")
        return attrs


def invoke(fn, **kwargs):
    try:
        return Response(fn(**kwargs))
    except lifecycle.InterpretationError as exc:
        return Response({"error": exc.code}, status=exc.status)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start(request):
    data = StartInput(data=request.data)
    data.is_valid(raise_exception=True)
    return invoke(lifecycle.begin, author=request.user, **data.validated_data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def detail(request, action_run_id):
    return invoke(lambda: lifecycle.snapshot(lifecycle.owned_parent(action_run_id, request.user)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def execute(request, action_run_id):
    data = ExecuteInput(data=request.data)
    data.is_valid(raise_exception=True)
    values = data.validated_data
    return invoke(lifecycle.execute, author=request.user, action_run_id=action_run_id,
        request_id=values["request_id"], expected_revision=values["expected_revision"],
        digest=values["source_digest"], consent=values["cloud_consent"])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def correct(request, action_run_id):
    data = CorrectionInput(data=request.data)
    data.is_valid(raise_exception=True)
    values = data.validated_data
    return invoke(lifecycle.correct, author=request.user, action_run_id=action_run_id,
        request_id=values["request_id"], expected_revision=values["expected_revision"],
        text=values.get("correction_text"), seed_id=values.get("correction_seed_id"))
