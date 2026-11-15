"""Narrow, scope-isolated claim endpoint; no general source/run reader."""
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from livewire.permissions import _HasServiceScope
from switchboard.auth import SwitchboardCoreAuthentication
from folio.api.serializers import FolioContextCommandSerializer
from folio.interpretation.recognition import claim
from heddle.errors import InterpretationError


class HasRecognitionClaimScope(_HasServiceScope):
    required_scope = "folio:recognition:claim"


class ClaimSerializer(FolioContextCommandSerializer):
    person_id = serializers.UUIDField()
    tenant_id = serializers.UUIDField()
    tenant_namespace = serializers.CharField(max_length=255)
    request_fingerprint = serializers.RegexField(r"^[a-f0-9]{64}$")


class RecognitionClaimView(APIView):
    authentication_classes = [SwitchboardCoreAuthentication]
    permission_classes = [HasRecognitionClaimScope]

    def post(self, request, execution_action_run_id):
        serializer = ClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(claim(execution_id=execution_action_run_id, **serializer.validated_data))
        except InterpretationError as exc:
            return Response({"error": exc.code}, status=exc.status)
