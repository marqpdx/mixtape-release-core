# mixtape/settings/dev.py
# Development settings for Phase 1

import os
import sys
from pathlib import Path

from django.db.backends.signals import connection_created
from django.dispatch import receiver
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)

# Import base settings
from .base import *


# Development overrides
DEBUG = True
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-unsafe-secret-key")

DJANGO_ENV = "dev"

# Allow all hosts in development
ALLOWED_HOSTS = ["*"]

# CORS - Allow frontend
# IMPORTANT: Cannot use CORS_ORIGIN_ALLOW_ALL with CORS_ALLOW_CREDENTIALS
# Must specify exact origins when credentials are enabled
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3010",  # Next.js frontend
]
CORS_ALLOW_CREDENTIALS = True

# JWT Cookie settings for development
# Note: SameSite=None allows cross-port cookies (localhost:3010 → localhost:8000)
# but browsers require Secure=True with SameSite=None, which requires HTTPS.
# For HTTP development, we use Lax and accept that refresh won't work cross-port.
# The access token (in memory) lasts 8 hours in dev, so you rarely need to re-login.
JWT_COOKIE_SECURE = False  # False for http in dev
JWT_COOKIE_SAMESITE = "Lax"  # Can't use "None" without Secure=True (HTTPS)

# Extend access token lifetime for development convenience
from datetime import timedelta


SIMPLE_JWT = {
    **SIMPLE_JWT,  # Inherit from base.py
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),  # Dev: 8 hours instead of 10 minutes
}

# Database - PostgreSQL (Phase 2: Required for Groups app with ArrayField)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "crossroads_stage"),
        "USER": os.getenv("DB_USER", "crossroads_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "mixtape_dev_password"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5433"),  # Docker exposes 5433->5432
    }
}



# ============================================================================
# DEFERRED: SQLite (Switched to PostgreSQL for Phase 2)
# ============================================================================
# SQLite doesn't support PostgreSQL-specific features like ArrayField
# which is used by the Groups app for membership roles
# ============================================================================
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# Email backend - console output in dev
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# for emailing
FRONTEND_URL = "http://localhost:3010"


# ============================================================================
# DEFERRED SETTINGS (Phase 2+)
# ============================================================================
# PostgreSQL database - uncomment when ready to use
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.getenv('DB_NAME', 'mixtape_db'),
#         'USER': os.getenv('DB_USER', 'mixtape_user'),
#         'PASSWORD': os.getenv('DB_PASSWORD', 'mixtape_dev_password'),
#         'HOST': os.getenv('DB_HOST', 'localhost'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#     }
# }

# S3 Storage - Phase 2
# STORAGES = {
#     "default": {
#         "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
#     },
#     "staticfiles": {
#         "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
#     },
# }

