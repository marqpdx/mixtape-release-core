from django.urls import path

from .mcp_token_views import MyMcpTokenRevokeView, MyMcpTokensView

# Mounted at /api/me/mcp-tokens/ (Service Trust ST-3, Switchboard SW-11.6).
urlpatterns = [
    path("", MyMcpTokensView.as_view(), name="my-mcp-tokens"),
    path("<uuid:token_id>/revoke/", MyMcpTokenRevokeView.as_view(), name="my-mcp-token-revoke"),
]
