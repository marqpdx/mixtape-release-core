from django.urls import path

from .person_views import (
    MyAIAccountsView,
    MyClaudeCheckView,
    MyClaudeConnectView,
    MyClaudeDisconnectView,
    MyClaudeLoginView,
)

# Mounted at /api/me/ai-accounts/ (Service Trust ST-3).
urlpatterns = [
    path("", MyAIAccountsView.as_view(), name="my-ai-accounts"),
    path("claude/connect/", MyClaudeConnectView.as_view(), name="my-claude-connect"),
    path("claude/login/", MyClaudeLoginView.as_view(), name="my-claude-login"),
    path("claude/check/", MyClaudeCheckView.as_view(), name="my-claude-check"),
    path("claude/disconnect/", MyClaudeDisconnectView.as_view(), name="my-claude-disconnect"),
]
