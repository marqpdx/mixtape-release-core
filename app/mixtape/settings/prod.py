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
FRONTEND_URL = "http://www.crossroads.place"


# Static files
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

# JWT Cookie settings for production

JWT_COOKIE_SECURE = True
JWT_COOKIE_SAMESITE = "None"

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
