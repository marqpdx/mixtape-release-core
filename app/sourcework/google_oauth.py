from __future__ import annotations

import json
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
OAUTH_SESSION_KEY = "sourcework_google_oauth"


@dataclass(frozen=True)
class GoogleOAuthStart:
    authorization_url: str
    state: str
    scopes: list[str]


def build_google_oauth_flow(*, redirect_uri: str, state: str | None = None):
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as exc:
        raise ImproperlyConfigured("google-auth-oauthlib is required for Google OAuth.") from exc

    client_config = _google_client_config()
    return Flow.from_client_config(
        client_config,
        scopes=[GMAIL_READONLY_SCOPE],
        redirect_uri=redirect_uri,
        state=state,
    )


def start_google_oauth(*, redirect_uri: str) -> GoogleOAuthStart:
    flow = build_google_oauth_flow(redirect_uri=redirect_uri)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return GoogleOAuthStart(
        authorization_url=authorization_url,
        state=state,
        scopes=[GMAIL_READONLY_SCOPE],
    )


def fetch_google_credentials(*, redirect_uri: str, state: str, authorization_response: str) -> dict:
    flow = build_google_oauth_flow(redirect_uri=redirect_uri, state=state)
    flow.fetch_token(authorization_response=authorization_response)
    return json.loads(flow.credentials.to_json())


def _google_client_config() -> dict:
    raw_config = getattr(settings, "SOURCEWORK_GOOGLE_OAUTH_CLIENT_CONFIG_JSON", "") or ""
    if raw_config:
        try:
            return json.loads(raw_config)
        except json.JSONDecodeError as exc:
            raise ImproperlyConfigured("SOURCEWORK_GOOGLE_OAUTH_CLIENT_CONFIG_JSON is not valid JSON.") from exc

    client_secrets_file = getattr(settings, "SOURCEWORK_GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "") or ""
    if client_secrets_file:
        try:
            with open(client_secrets_file, encoding="utf-8") as handle:
                return json.load(handle)
        except OSError as exc:
            raise ImproperlyConfigured("SOURCEWORK_GOOGLE_OAUTH_CLIENT_SECRETS_FILE could not be read.") from exc
        except json.JSONDecodeError as exc:
            raise ImproperlyConfigured("SOURCEWORK_GOOGLE_OAUTH_CLIENT_SECRETS_FILE is not valid JSON.") from exc

    raise ImproperlyConfigured(
        "Google OAuth is not configured. Set SOURCEWORK_GOOGLE_OAUTH_CLIENT_CONFIG_JSON "
        "or SOURCEWORK_GOOGLE_OAUTH_CLIENT_SECRETS_FILE."
    )
