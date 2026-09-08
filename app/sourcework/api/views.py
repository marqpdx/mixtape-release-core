import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from initiatives.models import Initiative
from sourcework.api.serializers import (
    ExternalConnectionSerializer,
    GmailLabelSerializer,
    ImportFromSourceSerializer,
    ImportLatestSerializer,
    SourceGrantSerializer,
    VerifyNameSerializer,
    WorkingSetSerializer,
)
from sourcework.google_oauth import (
    GMAIL_READONLY_SCOPE,
    OAUTH_SESSION_KEY,
    fetch_google_credentials,
    start_google_oauth,
)
from sourcework.models import (
    ExternalConnection,
    ExternalConnectionStatus,
    ProvisionalThing,
    SourceGrant,
    SourceGrantStatus,
    WorkingSet,
)
from sourcework.services import import_latest_from_source_grant, verify_provisional_name
from switchboard.source_grants import (
    SourceGrantAccessError,
    fetch_gmail_labels_for_connection,
    fetch_gmail_profile_from_credentials_payload,
)


User = get_user_model()
OAUTH_STATE_CACHE_PREFIX = "sourcework:google-oauth-state:"
OAUTH_STATE_CACHE_TTL_SECONDS = 10 * 60


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


class GoogleOAuthStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        redirect_uri = request.build_absolute_uri(f"/api/groups/{group.slug}/sourcework/google-oauth/callback")
        try:
            oauth_start = start_google_oauth(redirect_uri=redirect_uri)
        except ImproperlyConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        request.session[OAUTH_SESSION_KEY] = {
            "state": oauth_start.state,
            "group_id": str(group.id),
            "user_id": str(request.user.pk),
            "redirect_uri": redirect_uri,
        }
        cache.set(
            f"{OAUTH_STATE_CACHE_PREFIX}{oauth_start.state}",
            {
                "group_id": str(group.id),
                "user_id": str(request.user.pk),
                "redirect_uri": redirect_uri,
            },
            timeout=OAUTH_STATE_CACHE_TTL_SECONDS,
        )
        request.session.modified = True
        return Response(
            {
                "authorization_url": oauth_start.authorization_url,
                "state": oauth_start.state,
                "scopes": oauth_start.scopes,
            }
        )


class GoogleOAuthCallbackView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        group = _get_group(slug)
        state = str(request.GET.get("state") or "")
        session_state = request.session.get(OAUTH_SESSION_KEY) or {}
        cached_state = cache.get(f"{OAUTH_STATE_CACHE_PREFIX}{state}") or {}
        oauth_state = cached_state or {
            "group_id": session_state.get("group_id"),
            "user_id": session_state.get("user_id"),
            "redirect_uri": session_state.get("redirect_uri"),
        }
        if not state or (session_state.get("state") and session_state.get("state") != state):
            return Response({"detail": "Google OAuth state did not match."}, status=status.HTTP_400_BAD_REQUEST)
        if not oauth_state or oauth_state.get("group_id") != str(group.id):
            return Response({"detail": "Google OAuth group did not match."}, status=status.HTTP_400_BAD_REQUEST)
        owner = User.objects.filter(pk=oauth_state.get("user_id"), is_superuser=True).first()
        if not owner:
            return Response({"detail": "Google OAuth user could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)
        if request.GET.get("error"):
            return Response({"detail": f"Google OAuth returned error: {request.GET['error']}"}, status=status.HTTP_400_BAD_REQUEST)
        if not request.GET.get("code"):
            return Response({"detail": "Google OAuth callback did not include a code."}, status=status.HTTP_400_BAD_REQUEST)

        redirect_uri = oauth_state.get("redirect_uri") or request.build_absolute_uri(
            f"/api/groups/{group.slug}/sourcework/google-oauth/callback"
        )
        try:
            credentials = fetch_google_credentials(
                redirect_uri=redirect_uri,
                state=str(request.GET.get("state") or ""),
                authorization_response=request.build_absolute_uri(),
            )
        except ImproperlyConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"detail": f"Google OAuth callback failed: {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        account_email = "google-gmail"
        profile = {}
        try:
            profile = fetch_gmail_profile_from_credentials_payload(credentials, scopes=[GMAIL_READONLY_SCOPE])
            account_email = str(profile.get("emailAddress") or account_email)
        except SourceGrantAccessError:
            pass
        connection = ExternalConnection.objects.create(
            group=group,
            owner=owner,
            provider="google_gmail",
            provider_account_id=str(account_email),
            display_name=f"Google Mail - {account_email}" if account_email != "google-gmail" else "Google Mail",
            credential_reference="encrypted:credential_payload",
            credential_payload=json.dumps(credentials),
            provider_scopes=[GMAIL_READONLY_SCOPE],
            status=ExternalConnectionStatus.READY,
            connected_at=timezone.now(),
            refreshed_at=timezone.now(),
            metadata={"adapter": "switchboard_gmail_v1", "oauth_flow": "google_web_server", "gmail_profile": profile},
        )
        cache.delete(f"{OAUTH_STATE_CACHE_PREFIX}{state}")
        request.session.pop(OAUTH_SESSION_KEY, None)
        request.session.modified = True
        return HttpResponse(
            "<!doctype html><title>Google Mail connected</title>"
            "<p>Google Mail connected. You can close this tab and return to Mixtape.</p>"
            f"<p>Connection: {connection.display_name}</p>"
        )


class ConnectionGmailLabelsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug, connection_id):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        connection = get_object_or_404(
            ExternalConnection,
            id=connection_id,
            group=group,
            provider="google_gmail",
            status=ExternalConnectionStatus.READY,
        )
        try:
            labels = fetch_gmail_labels_for_connection(connection)
        except SourceGrantAccessError as exc:
            return Response({"detail": exc.detail, "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"labels": GmailLabelSerializer(labels, many=True).data})


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
        try:
            result = import_latest_from_source_grant(
                grant,
                user=request.user,
                adapter_key="manual_v1",
                limit=5,
                payload={"messages": serializer.validated_data["messages"]},
            )
        except Exception:
            raise
        return Response(result, status=status.HTTP_201_CREATED)


class SourceGrantImportFromSourceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, grant_id):
        if not _superuser_required(request):
            return _forbidden()
        group = _get_group(slug)
        grant = get_object_or_404(SourceGrant, id=grant_id, connection__group=group, status=SourceGrantStatus.ACTIVE)
        serializer = ImportFromSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = import_latest_from_source_grant(
            grant,
            user=request.user,
            adapter_key=serializer.validated_data["adapter"],
            limit=serializer.validated_data["limit"],
        )
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
