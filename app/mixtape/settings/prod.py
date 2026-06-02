# mixtape/settings/prod.py

# Production settings for Phase 1

import os
import sys
from pathlib import Path

import environ
from dotenv import load_dotenv


env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.prod", override=True)

# Import base settings
from .base import *

from django.core.exceptions import ImproperlyConfigured

_required = {
    "DJANGO_SECRET_KEY": SECRET_KEY,
    "ACCESS_TOKEN_SIGNING_KEY": ACCESS_TOKEN_SIGNING_KEY,
    "EMAIL_HOST_USER": EMAIL_HOST_USER,
    "EMAIL_HOST_PASSWORD": EMAIL_HOST_PASSWORD,
}
for _var, _val in _required.items():
    if not _val:
        raise ImproperlyConfigured(f"{_var} must be set in production")


# Production settings
DEBUG = False
DJANGO_ENV = "prod"

# Database - PostgreSQL for production
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql_psycopg2',
#         "NAME": os.getenv("POSTGRES_DB", "crossroads_prod"),
#         "USER": os.getenv("POSTGRES_USER", "crossroads_user"),
#         "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
#         'HOST': os.getenv("POSTGRES_HOST", "localhost"),
#         'PORT': os.getenv("POSTGRES_PORT", "5432"),
#     }
# }

# Parse DATABASE_URL
DATABASES = {
    "default": env.db("DATABASE_URL")
}

# for emailing
FRONTEND_URL = "https://www.crossroads.place"

OPS_APPLICATION_SURFACES = {
    "mixtape-web": {
        "label": "Mixtape Web",
        "surface_type": "nextjs",
        "provider": "vercel",
        "environment": "production",
        "endpoint": "https://www.crossroads.place/app",
        "probe_paths": ["/login"],
    },
    "crossroads-web": {
        "label": "Crossroads Web",
        "surface_type": "nextjs",
        "provider": "vercel",
        "environment": "production",
        "endpoint": "https://www.crossroads.place",
        "probe_paths": ["/"],
    },
    "django-api": {
        "label": "Django API",
        "surface_type": "api",
        "provider": "systemd",
        "environment": "production",
        "endpoint": "https://api.crossroads.place",
        "probe_paths": ["/health/"],
    },
}

OPS_LIVEWIRE_MONITOR = {
    "label": "Livewire",
    "provider": "socketio",
    "environment": "production",
    "endpoint": "https://chat.crossroads.place",
    "probe_path": "/socket.io/?EIO=4&transport=polling",
    "notes": [
        "Probes the public Socket.IO handshake through the deployed chat endpoint.",
        "This does not validate authenticated chat traffic or room subscriptions.",
    ],
}

OPS_BACKUP_MONITORS = {
    "postgres": {
        "label": "Postgres Backups",
        "timer_unit": "pg-backup.timer",
        "service_unit": "pg-backup.service",
        "upload_unit": "pg-backup-upload.service",
        "stamp_file": "/var/lib/backup-stamps/pg-backup.last_success",
        "archive_directory": "/var/backups/postgres",
        "expected_archives": [
            {"label": "crossroads_prod", "prefix": "crossroads_prod_", "suffix": ".sql.gz"},
            {"label": "listmonk_prod", "prefix": "listmonk_prod_", "suffix": ".sql.gz"},
        ],
        "interval_seconds": 72 * 3600,
        "off_host_required": True,
    },
    "seaweedfs": {
        "label": "SeaweedFS Backups",
        "timer_unit": "seaweed-backup.timer",
        "service_unit": "seaweed-backup.service",
        "upload_unit": "seaweed-backup-upload.service",
        "stamp_file": "/var/lib/backup-stamps/seaweed-backup.last_success",
        "archive_directory": "/var/backups/seaweed",
        "expected_archives": [
            {"label": "seaweed_snapshot", "prefix": "seaweed_", "suffix": ".tar.gz"},
        ],
        "interval_seconds": 72 * 3600,
        "off_host_required": True,
    },
}


# Static files
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

# JWT Cookie settings for production

JWT_COOKIE_SECURE = True
JWT_COOKIE_SAMESITE = "None"

SESSION_COOKIE_AGE = 86400  # 1 day; explicit to avoid defaulting to 14-day Django default
SESSION_COOKIE_DOMAIN = ".crossroads.place"
CSRF_COOKIE_DOMAIN = ".crossroads.place"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SAMESITE = "None"

# CORS - Production domains
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "https://www.crossroads.place",
    "https://crossroads.place",
    "https://www.mindfulbrilliance.com",
    "https://mindfulbrilliance.com",
]

# CSRF - Production domains
CSRF_TRUSTED_ORIGINS = [
    "https://www.crossroads.place",
    "https://crossroads.place",
]

# Allowed hosts
ALLOWED_HOSTS = [
    "api.crossroads.place",      # API subdomain (MUST have this!)
    "www.crossroads.place",      # Frontend domain
    "crossroads.place",          # Main domain
    "70.34.212.85",              # Server IP address
    "localhost",                 # For local testing
    "127.0.0.1",                 # For local testing
]

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/crossroads/django.log",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}

# ============================================================================
# DEFERRED SETTINGS (Phase 2+)
# ============================================================================
# S3 Storage - Phase 2
# STORAGES = {
#     "default": {
#         "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
#     },
#     "staticfiles": {
#         "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
#     },
# }
