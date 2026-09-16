import logging

import celery.exceptions
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from clio.api.serializers import (
    KeeperDeregisterSerializer,
    KeeperFindingSerializer,
    KeeperFindingSubmitSerializer,
    KeeperRegisterSerializer,
    KeeperRegistrationSerializer,
    KeeperRouteQuestionSerializer,
)
from accounts.api.permissions import IsSuperUser
from clio import services as clio_services
from clio.models import KeeperFinding, KeeperRegistration, KeeperRegistrationStatus
from livewire.auth import InternalServiceAuthentication
from livewire.permissions import HasKeeperFindingScope, HasKeeperRouteScope, HasKeeperWriteScope
from mixtape.celery_app import app as celery_app

logger = logging.getLogger(__name__)


class KeeperRegisterView(APIView):
    """
    AD-10 registration endpoint. Thin wrapper over clio.services.register_keeper —
    see that function for the actual restart/re-registration semantics (AD-5).
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperWriteScope]

    def post(self, request):
        serializer = KeeperRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        registration = clio_services.register_keeper(
            keeper_id=data["keeper_id"],
            keeper_name=data["keeper_name"],
            owner_subsystem=data["owner_subsystem"],
            watch_scope=data["watch_scope"],
            question_shapes=data.get("question_shapes") or [],
            finding_cadence=data["finding_cadence"],
            closing_mode=data.get("closing_mode"),
            instance_params=data.get("instance_params") or {},
        )
        return Response(KeeperRegistrationSerializer(registration).data, status=status.HTTP_201_CREATED)


class KeeperDeregisterView(APIView):
    """
    AD-5 deregistration endpoint. Thin wrapper over clio.services.deregister_keeper.
    closing_mode in the request body overrides the registration's own
    declared preference for this deregistration only.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperWriteScope]

    def post(self, request, keeper_id):
        serializer = KeeperDeregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        get_object_or_404(KeeperRegistration, keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE)
        closing_mode_override = serializer.validated_data.get("closing_mode")
        registration = clio_services.deregister_keeper(keeper_id=keeper_id, closing_mode=closing_mode_override)
        return Response(
            {"keeper_id": keeper_id, "closing_mode": closing_mode_override or registration.closing_mode},
            status=status.HTTP_200_OK,
        )


class KeeperRouteView(APIView):
    """
    AD-11 routing endpoint. Matches an incoming intent against active
    registrations' denormalized `intents`, dispatches the matched
    question_shape's answer_task as a Celery task by name (send_task —
    Clio never imports a Keeper's task module, per AD-3's "does not inspect
    internal logic beyond the registered payload"), awaits the result, and
    relays it unmodified. no_keeper_available is a valid non-error response.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperRouteScope]

    def post(self, request):
        serializer = KeeperRouteQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        intent = serializer.validated_data["intent"]
        question_params = serializer.validated_data.get("question_params") or {}

        candidates = list(
            KeeperRegistration.objects.filter(
                status=KeeperRegistrationStatus.ACTIVE, intents__contains=[intent]
            ).order_by("-registered_at")
        )
        if not candidates:
            return Response({"intent": intent, "status": "no_keeper_available"})

        registration = candidates[0]
        if len(candidates) > 1:
            logger.warning(
                "Intent '%s' matched %d active Keeper registrations (%s); "
                "most-recently-registered wins: '%s'. Duplicate intent registration is a misconfiguration.",
                intent,
                len(candidates),
                [c.keeper_id for c in candidates],
                registration.keeper_id,
            )

        answer_task_name = next(
            (shape["answer_task"] for shape in registration.question_shapes if shape.get("intent") == intent),
            None,
        )
        if not answer_task_name:
            logger.error(
                "Keeper '%s' has intent '%s' in its denormalized intents array but no matching "
                "question_shapes entry — registration data is inconsistent.",
                registration.keeper_id,
                intent,
            )
            return Response({"intent": intent, "status": "no_keeper_available"})

        async_result = celery_app.send_task(
            answer_task_name, args=[registration.keeper_id, intent, question_params]
        )
        try:
            answer = async_result.get(timeout=settings.CLIO_KEEPER_ROUTE_TIMEOUT_SECONDS)
        except celery.exceptions.TimeoutError:
            logger.warning("Keeper '%s' did not answer intent '%s' within timeout.", registration.keeper_id, intent)
            return Response(
                {"intent": intent, "keeper_id": registration.keeper_id, "detail": "Keeper did not respond in time."},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Keeper '%s' answer_task '%s' raised an error.", registration.keeper_id, answer_task_name)
            return Response(
                {"intent": intent, "keeper_id": registration.keeper_id, "detail": f"Keeper task failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(answer)


class KeeperFindingSubmitView(APIView):
    """
    AD-12 proactive finding submission — store-and-defer scope (K-3, see
    keeper-adr-status.md). Validates keeper_id against an active
    registration (unregistered Keepers cannot submit) and durably stores
    the finding. Does NOT surface it anywhere — no ClioState/signal-salience
    integration in this pass; that's a deliberate, separate follow-up.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperFindingScope]

    def post(self, request):
        serializer = KeeperFindingSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            finding = clio_services.submit_finding(
                keeper_id=data["keeper_id"],
                finding_type=data["finding_type"],
                finding_body=data.get("finding_body") or {},
                suggested_clio_signal=data["suggested_clio_signal"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(KeeperFindingSerializer(finding).data, status=status.HTTP_201_CREATED)


class KeeperFindingListView(APIView):
    """
    Human-readable inspection of stored findings — the "queryable" half of
    K-3's store-and-defer scope. Not a surfacing mechanism; just makes
    stored findings visible without needing direct DB/admin access.
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def get(self, request):
        qs = KeeperFinding.objects.all().order_by("-submitted_at")
        keeper_id = request.query_params.get("keeper_id")
        if keeper_id:
            qs = qs.filter(keeper_id=keeper_id)
        return Response(KeeperFindingSerializer(qs, many=True).data)


class KeeperRegistryListView(APIView):
    """
    Human-readable registry inspection (AD-10: watch_scope is "used for
    human-readable registry inspection"). Active registrations by default;
    pass ?status=archived to inspect the dormant store.
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def get(self, request):
        status_filter = request.query_params.get("status", KeeperRegistrationStatus.ACTIVE)
        qs = KeeperRegistration.objects.filter(status=status_filter).order_by("-registered_at")
        return Response(KeeperRegistrationSerializer(qs, many=True).data)
