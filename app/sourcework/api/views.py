from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
    Initiative,
)
from sourcework.api.serializers import (
    ExternalConnectionSerializer,
    ImportLatestSerializer,
    SourceGrantSerializer,
    VerifyNameSerializer,
    WorkingSetSerializer,
)
from sourcework.models import (
    ExternalConnection,
    ExternalConnectionStatus,
    ProvisionalThing,
    SourceGrant,
    SourceGrantStatus,
    WorkingSet,
)
from sourcework.services import import_latest_messages, verify_provisional_name


_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


def _get_group(slug: str) -> Group:
    return get_object_or_404(Group, slug=slug)


def _superuser_required(request) -> bool:
    return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def _forbidden() -> Response:
    return Response({"detail": "Superuser access required."}, status=status.HTTP_403_FORBIDDEN)


class ConnectionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        qs = ExternalConnection.objects.filter(group=group).order_by("-created_at")
        return Response(ExternalConnectionSerializer(qs, many=True).data)

    def post(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        data = request.data.copy()
        connection = ExternalConnection.objects.create(
            group=group,
            owner=request.user,
            provider=data.get("provider") or "google_gmail",
            provider_account_id=data.get("provider_account_id") or "",
            display_name=data.get("display_name") or "Google Mail",
            credential_reference=data.get("credential_reference") or "",
            provider_scopes=data.get("provider_scopes") or ["gmail.readonly"],
            status=data.get("status") or ExternalConnectionStatus.READY,
            connected_at=timezone.now(),
            metadata=data.get("metadata") or {"adapter": "manual_v1"},
        )
        return Response(ExternalConnectionSerializer(connection).data, status=status.HTTP_201_CREATED)


class SourceGrantListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        qs = SourceGrant.objects.filter(connection__group=group).select_related("connection", "initiative")
        return Response(SourceGrantSerializer(qs, many=True).data)

    def post(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        connection = get_object_or_404(ExternalConnection, id=request.data.get("connection"), group=group)
        initiative = None
        if request.data.get("initiative"):
            initiative = get_object_or_404(Initiative, id=request.data["initiative"])
            if str(initiative.sponsor_object_id) != str(group.pk):
                return Response({"detail": "Initiative does not belong to this group."}, status=status.HTTP_400_BAD_REQUEST)

        grant, _ = SourceGrant.objects.get_or_create(
            connection=connection,
            initiative=initiative,
            resource_kind=request.data.get("resource_kind") or "gmail_label",
            resource_id=request.data.get("resource_id") or "Recruiters",
            defaults={
                "display_name": request.data.get("display_name") or "Recruiters",
                "capabilities": ["read"],
                "created_by": request.user,
                "metadata": {"source_boundary": "switchboard_enforced"},
            },
        )
        if grant.status != SourceGrantStatus.ACTIVE:
            grant.status = SourceGrantStatus.ACTIVE
            grant.revoked_at = None
            grant.save(update_fields=["status", "revoked_at", "updated_at"])
        return Response(SourceGrantSerializer(grant).data, status=status.HTTP_201_CREATED)


class SourceGrantImportLatestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, grant_id):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        grant = get_object_or_404(SourceGrant, id=grant_id, connection__group=group, status=SourceGrantStatus.ACTIVE)
        serializer = ImportLatestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_run = ActionRun.objects.create(
            initiative=grant.initiative,
            source_grant=grant,
            tool_name="source.gmail.import_latest_manual_v1",
            status=ActionRunStatus.RUNNING,
            execution_mode=ActionRunExecutionMode.LOCAL,
            service_name="switchboard",
            tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)),
            tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE)),
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(request.user.pk),
            request_payload={
                "source_grant_id": str(grant.id),
                "resource_kind": grant.resource_kind,
                "resource_id": grant.resource_id,
                "message_count": len(serializer.validated_data["messages"]),
                "adapter": "manual_v1",
            },
        )
        try:
            result = import_latest_messages(grant, serializer.validated_data["messages"], user=request.user)
        except Exception as exc:
            action_run.status = ActionRunStatus.FAILED
            action_run.error_payload = {"error": str(exc)}
            action_run.completed_at = timezone.now()
            action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
            raise

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = result
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        return Response(result, status=status.HTTP_201_CREATED)


class WorkingSetListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        qs = WorkingSet.objects.filter(group=group).prefetch_related(
            "memberships__provisional_thing__evidence"
        )
        return Response(WorkingSetSerializer(qs, many=True).data)


class ProvisionalThingVerifyNameView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, thing_id):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        thing = get_object_or_404(ProvisionalThing, id=thing_id, group=group)
        serializer = VerifyNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verify_provisional_name(
            thing,
            preferred_name=serializer.validated_data["preferred_name"],
            note=serializer.validated_data.get("note") or "",
            user=request.user,
        )
        from sourcework.services import _refresh_working_set_summary

        first_membership = None
        for membership in thing.working_set_memberships.select_related("working_set"):
            first_membership = first_membership or membership
            _refresh_working_set_summary(membership.working_set)
        if not first_membership:
            return Response({"detail": "Name verified, but this provisional item is not in a Working Set."})
        return Response(WorkingSetSerializer(first_membership.working_set).data)
