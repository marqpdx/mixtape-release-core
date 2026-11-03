# tenant_runtime/api/mcp_token_views.py
"""
Your own MCP runtime tokens: list, mint, and revoke (Service Trust ST-3,
Switchboard SW-11.6).

Every view finds tokens from request.user alone (decision S5) -- no route
takes a person id, so nobody can see or revoke another person's tokens,
staff included. The raw token value is returned exactly once, from the
mint response; it is never stored and can never be shown again.

Mounted at /api/me/mcp-tokens/.
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from tenant_runtime.models import McpRuntimeToken, TenantClaudeRuntime
from tenant_runtime.resolve import CLAUDE, get_person_runtime


def _serialize(token: McpRuntimeToken) -> dict:
    return {
        "id": str(token.id),
        "token_prefix": token.token_prefix,
        "group_id": str(token.group_id) if token.group_id else None,
        "group_name": token.group.title if token.group_id and token.group else None,
        "scopes": token.scopes,
        "created_at": token.created_at.isoformat(),
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
        "is_valid": token.is_valid,
    }


class MyMcpTokensView(APIView):
    """GET: list your tokens. POST: mint a new one (requires a ready Claude runtime)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tokens = McpRuntimeToken.objects.filter(person=request.user).select_related("group")
        return Response({"tokens": [_serialize(t) for t in tokens]})

    def post(self, request):
        runtime = get_person_runtime(request.user, CLAUDE)
        if runtime is None or runtime.status != TenantClaudeRuntime.STATUS_READY:
            return Response(
                {"detail": "Connect your Claude account before minting an MCP token."},
                status=status.HTTP_409_CONFLICT,
            )

        group = None
        group_id = request.data.get("group_id")
        if group_id:
            group = get_object_or_404(Group, pk=group_id)
            if not group.is_member(request.user):
                return Response(
                    {"detail": "You are not a member of that Group."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        token, raw_token = McpRuntimeToken.issue(person=request.user, runtime=runtime, group=group)
        return Response(
            {"token": raw_token, **_serialize(token)},
            status=status.HTTP_201_CREATED,
        )


class MyMcpTokenRevokeView(APIView):
    """POST /api/me/mcp-tokens/<id>/revoke/ -- revoke one of your own tokens."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token_id):
        token = get_object_or_404(McpRuntimeToken, pk=token_id, person=request.user)
        token.revoke()
        return Response(_serialize(token))
