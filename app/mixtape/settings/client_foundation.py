# mixtape/settings/client_foundation.py
#
# Foundation-tier settings profile for client installs.
# Auth + Catalyst only — no real-time services, no AI/search, no newsletters.
#
# Usage: DJANGO_SETTINGS_MODULE=mixtape.settings.client_foundation
#
# Service composition tiers:
#   client_foundation  — auth + Catalyst (this file)
#   client_search      — foundation + Stackroom (future)
#   client_studio      — search + Inkwell + Switchboard (future)

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import environ

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

from .base import *  # noqa: F403, F401

from django.core.exceptions import ImproperlyConfigured

# ============================================================================
# ENVIRONMENT
# ============================================================================
DEBUG = False
DJANGO_ENV = "client_foundation"

# ============================================================================
# REQUIRED VARS — fail fast
# ============================================================================
_required = {
    "DJANGO_SECRET_KEY": SECRET_KEY,  # noqa: F405
    "ACCESS_TOKEN_SIGNING_KEY": ACCESS_TOKEN_SIGNING_KEY,  # noqa: F405
}
for _var, _val in _required.items():
    if not _val:
        raise ImproperlyConfigured(f"{_var} must be set for client_foundation")

# ============================================================================
# DATABASE
# ============================================================================
DATABASES = {
    "default": env.db("DATABASE_URL")
}

# ============================================================================
# INSTALLED APPS — auth + Catalyst only
# ============================================================================
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_filters",
    "django_extensions",

    # Third-party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "oauth2_provider",
    "storages",

    # Auth / user layer
    "users",           # CustomUser
    "accounts",        # JWT auth, login endpoints
    "profiles",        # UserProfile, Member API

    # Core platform (Catalyst depends on these)
    "fundamentals",    # BaseModel
    "groups",          # Group model — tenant registry, TenantMiddleware reads here
    "classifications", # Tags (used by groups)
    "contexts",        # Context management
    "activity",        # Notifications (GroupMembership signals)
    "identity",        # Emblems
    "assets",          # File handling
    "utils",           # Shared utilities

    # Intake + provisioning
    "prospects",       # BusinessProspect — intake form, Prospect→Group migration
    "business",        # BusinessProspect depends on business models

    # Public-facing API
    "public_api",      # /api/public/* (get-started endpoint lives here)

    # Catalyst — the product
    "catalyst",        # Codex provisioning, activate_catalyst_tenant command

    # Admin surface
    "studio",          # Group / member admin surface
    "ops",             # Health check + ops dashboard backend
]

# ============================================================================
# CATALYST — required for activate_catalyst_tenant to run
# ============================================================================
# Override these in .env on the server.
#   CATALYST_CODEX_ROOT=/srv/codex
#   CATALYST_SEED_PATH=/home/deploy/release/mixtape-release-catalyst
CATALYST_CODEX_ROOT = Path(os.getenv("CATALYST_CODEX_ROOT", "/srv/codex"))
CATALYST_SEED_PATH = Path(os.getenv("CATALYST_SEED_PATH", "")) if os.getenv("CATALYST_SEED_PATH") else None

INTAKE_FORM_ENABLED = True

# ============================================================================
# ALLOWED HOSTS — wildcard subdomain pattern
# ============================================================================
ALLOWED_HOSTS = [
    ".crossroads.place",   # covers *.crossroads.place and crossroads.place
    "localhost",
    "127.0.0.1",
]

# ============================================================================
# CORS — Vercel-hosted Crossroads frontend + all *.crossroads.place subdomains
# ============================================================================
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "https://crossroads.place",
    "https://www.crossroads.place",
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.crossroads\.place$",
]

# ============================================================================
# CSRF + SESSION COOKIES — scoped to *.crossroads.place
# ============================================================================
SESSION_COOKIE_DOMAIN = ".crossroads.place"
CSRF_COOKIE_DOMAIN = ".crossroads.place"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SAMESITE = "None"
SESSION_COOKIE_AGE = 86400

CSRF_TRUSTED_ORIGINS = [
    "https://*.crossroads.place",
    "https://crossroads.place",
]

JWT_COOKIE_SECURE = True
JWT_COOKIE_SAMESITE = "None"

# ============================================================================
# STATIC / MEDIA
# ============================================================================
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

# ============================================================================
# LOGGING
# ============================================================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "mixtape": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
