import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from clio.api.serializers import (
    KeeperDeregisterSerializer,
    KeeperRegisterSerializer,
    KeeperRegistrationSerializer,
)
from accounts.api.permissions import IsSuperUser
from clio.models import KeeperClosingMode, KeeperRegistration, KeeperRegistrationStatus
from livewire.auth import InternalServiceAuthentication
from livewire.permissions import HasKeeperWriteScope

logger = logging.getLogger(__name__)


def _close_registration(registration: KeeperRegistration, *, closing_mode: str) -> None:
    """
    Apply AD-5's drop/archive semantics. Drop is a real delete; archive
    retains the full row (payload, owner, timestamp) and is never deleted.
    """
    if closing_mode == KeeperClosingMode.DROP:
        registration.delete()
        return
    registration.status = KeeperRegistrationStatus.ARCHIVED
    registration.archived_at = timezone.now()
    registration.save(update_fields=["status", "archived_at", "updated_at"])


class KeeperRegisterView(APIView):
    """
    AD-10 registration endpoint. A restarted Keeper is always a new
    registration (AD-5) — if an active registration already exists under the
    same keeper_id, it is implicitly closed (using its own declared closing
    mode) before the new one is created, rather than erroring.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperWriteScope]

    def post(self, request):
        serializer = KeeperRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        existing = KeeperRegistration.objects.filter(
            keeper_id=data["keeper_id"], status=KeeperRegistrationStatus.ACTIVE
        ).first()
        if existing:
            logger.info(
                "Keeper '%s' re-registered while an active registration existed; closing prior registration (mode=%s).",
                data["keeper_id"],
                existing.closing_mode,
            )
            _close_registration(existing, closing_mode=existing.closing_mode)

        question_shapes = data.get("question_shapes") or []
        registration = KeeperRegistration.objects.create(
            keeper_id=data["keeper_id"],
            keeper_name=data["keeper_name"],
            owner_subsystem=data["owner_subsystem"],
            watch_scope=data["watch_scope"],
            question_shapes=question_shapes,
            intents=[shape["intent"] for shape in question_shapes],
            finding_cadence=data["finding_cadence"],
            closing_mode=data.get("closing_mode") or KeeperClosingMode.ARCHIVE,
            instance_params=data.get("instance_params") or {},
        )
        return Response(KeeperRegistrationSerializer(registration).data, status=status.HTTP_201_CREATED)


class KeeperDeregisterView(APIView):
    """
    AD-5 deregistration endpoint. closing_mode in the request body overrides
    the registration's own declared preference for this deregistration only;
    omit it to use what was declared at registration time.
    """

    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasKeeperWriteScope]

    def post(self, request, keeper_id):
        serializer = KeeperDeregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        registration = get_object_or_404(
            KeeperRegistration, keeper_id=keeper_id, status=KeeperRegistrationStatus.ACTIVE
        )
        closing_mode = serializer.validated_data.get("closing_mode") or registration.closing_mode
        _close_registration(registration, closing_mode=closing_mode)
        return Response({"keeper_id": keeper_id, "closing_mode": closing_mode}, status=status.HTTP_200_OK)


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
