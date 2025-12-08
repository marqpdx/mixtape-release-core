import os
from datetime import timedelta
from pathlib import Path

import environ
from dotenv import load_dotenv


# Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))

# TODO - sort this: https://django-environ.readthedocs.io/en/latest/quickstart.html
env = environ.Env(
    ON_SERVER=(bool, True),
    LOGGING_LEVEL=(str, "INFO"),
    DEBUG=(bool, False)
)

SITE_ADMIN_EMAIL = "marqpdx@gmail.com"
CONTACT_NOTIFICATION_EMAIL = "marqpdx@gmail.com"

DEFAULT_FROM_EMAIL = "The Mixtape Team <info@mindfulbrilliance.com>"

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-unsafe-secret-key")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# SECRET_KEY = 'django-insecure-=voin^2bh$c%_azyddk3kdk3kdk22s1dv-#_x_8xu9+7vkouk*p-$d0'

# SECURITY WARNING: don't run with debug turned on in production!
# DEBUG = True

ALLOWED_HOSTS = ["*"]

# ============================================================================
# QDRANT & INKWELL AI SERVICES
# ============================================================================
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

INKWELL_BASE_URL = os.getenv(
    "INKWELL_BASE_URL",
    "https://inkwell.crossroads.place",  # default if not set
).rstrip("/")

# Application definition

# ============================================================================
# PHASE 1: MINIMAL INSTALLED_APPS (Authentication + Profiles Only)
# ============================================================================
# Removed apps: ai, chat, writing, groups, assets, identity, and many others
# These will be added back incrementally in future phases
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
    "corsheaders",          # CORS handling for frontend
    "rest_framework",       # Django REST Framework
    "rest_framework_simplejwt",  # JWT authentication
    "storages",            # S3 and cloud storage support

    # Local - MINIMAL for Phase 1
    "accounts",        # Authentication (JWT, login, /auth/me)
    "activity",        # User activity tracking and notifications
    "assets",          # Asset management (deferred to Phase 2)
    "chat",            # Chat app, socket.io
    "classifications", # Tags and categories system
    "contexts",        # Context management
    "dispatch",        # Collaborative writing (yjs-based real-time editing)
    "fundamentals",    # BaseModel (timestamps, soft delete)
    "groups",          # Group model, GroupMembership, Invitations (Phase 2)
    "inkwell",         # AI services, RAG, synopsis generation
    "profiles",        # UserProfile, Member API
    "users",           # CustomUser, Role models
    "utils",           # Utility functions and helpers
    "writing",         # Writing app
]

INSTALLED_APPS += ["rest_framework_simplejwt.token_blacklist"]

# ============================================================================
# DEFERRED APPS (Add back in later phases):
# - Phase 2: 'identity' (avatars), 'assets' (file storage)
# - Phase 3: 'groups', 'members' (if needed)
# - Phase 4+: 'ai', 'chat', 'writing', 'activity', 'almanac', 'classifications',
#             'contact', 'content', 'contexts', 'dispatch', 'earthlab',
#             'lantern', 'library', 'threadworks', 'utils'
# ============================================================================


# ============================================================================
# GROUPS (Phase 2)
# ============================================================================
MIXTAPE_DEFAULT_GROUP_NAME = os.getenv("MIXTAPE_DEFAULT_GROUP_NAME", "Crossroads")
MIXTAPE_DEFAULT_GROUP_SLUG = os.getenv("MIXTAPE_DEFAULT_GROUP_SLUG", "crossroads")
MIXTAPE_DEFAULT_GROUP_UUID_NAMESPACE = os.getenv("MIXTAPE_DEFAULT_GROUP_UUID_NAMESPACE", "mixtape://default-group")


# ============================================================================
# LIVEWIRE (WebSocket/Real-time - Deferred to Phase 4+)
# ============================================================================
# LIVEWIRE_JWT_SECRET = os.getenv("LIVEWIRE_JWT_SECRET")
# LIVEWIRE_JWT_ALG = os.getenv("LIVEWIRE_JWT_ALG", "HS256")
# LIVEWIRE_JWT_ISS = os.getenv("LIVEWIRE_JWT_ISS", "mixtape")
# LIVEWIRE_JWT_AUD = os.getenv("LIVEWIRE_JWT_AUD", "livewire")
# LIVEWIRE_URL = os.getenv("LIVEWIRE_URL", "ws://127.0.0.1:5001")


# ============================================================================
# SERVICE JWT (Microservices - Deferred to Phase 4+)
# ============================================================================
# SERVICE_JWT_SECRET = os.getenv("SERVICE_JWT_SECRET")
# SERVICE_JWT_ALG = os.getenv("SERVICE_JWT_ALG", "HS256")
# SERVICE_JWT_ISS = os.getenv("SERVICE_JWT_ISS", "mixtape")
# SERVICE_JWT_AUD = os.getenv("SERVICE_JWT_AUD", "django-api")
# SERVICE_JWT_TTL_SECONDS = int(os.getenv("SERVICE_JWT_TTL_SECONDS", "600"))


# User info
AUTH_USER_MODEL = "users.CustomUser"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",                  # 🔍 Handles CORS first to avoid preflight issues
    "django.middleware.security.SecurityMiddleware",          # 🛡️ Security headers like HSTS
    "django.contrib.sessions.middleware.SessionMiddleware",   # 🗂️ Session management for user sessions
    "django.middleware.common.CommonMiddleware",              # 🔄 Basic middleware like GZip, Conditional GET
    "django.middleware.csrf.CsrfViewMiddleware",              # 🔒 CSRF protection middleware
    "django.contrib.auth.middleware.AuthenticationMiddleware",# 🔑 Populates `request.user` ✅
    # 'users.middleware.AuthorizationMiddleware',               # 🚀 Our custom Authorization Middleware 🔥
    "django.contrib.messages.middleware.MessageMiddleware",   # ✉️ Flash messages for users
    "django.middleware.clickjacking.XFrameOptionsMiddleware", # ❌ Prevents clickjacking
]

# RolePermissionMiddleware goes after AuthenticationMiddleware because it needs the request.user.
# It goes before any view logic, so unauthorized access is blocked early.
# It allows us to fail fast and reduce load on DRF.

ROOT_URLCONF = "mixtape.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mixtape.wsgi.application"



# ============================================================================
# FILE STORAGE (Deferred to Phase 2)
# ============================================================================
# Using default Django file storage (local filesystem) for Phase 1
# Will add S3/cloud storage in Phase 2 when we implement image uploads
# ============================================================================
# DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "admin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_SIGNATURE_VERSION = os.getenv("AWS_S3_SIGNATURE_VERSION", "s3v4")
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:9000")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "mixtape-assets")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "us-east-1")
AWS_S3_USE_SSL = os.getenv("AWS_S3_USE_SSL", "false").lower() == "true"

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        # If you want, you can pass options here instead of via AWS_*,
        # but the classic AWS_* settings are fine too.
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


# ============================================================================
# EARTHLAB (Deferred to Phase 4+)
# ============================================================================
# EARTHLAB_AUTO_CREATE_DEFAULT_CHAT = False


# ============================================================================
# LISTMONK (Deferred to Phase 3+)
# ============================================================================
# Email campaign settings - will add back when we implement newsletters
# LISTMONK_BASE_URL = os.getenv('LISTMONK_BASE_URL')
# LISTMONK_AUTH = (
#     os.getenv('LISTMONK_USERNAME'),
#     os.getenv('LISTMONK_PASSWORD')
# )



# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "in-v3.mailjet.com"
EMAIL_PORT = "587"
EMAIL_HOST_USER = "REDACTED-MAILJET-API-KEY"
EMAIL_HOST_PASSWORD = "REDACTED-MAILJET-SECRET-KEY"
EMAIL_USE_TLS = True


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"
APPEND_SLASH=False

# ============================================================================
# SPONSOR MODELS (Polymorphic Content)
# ============================================================================
# Used by BaseContent for polymorphic sponsor relationships
# Maps token strings to model labels for content type resolution
# ============================================================================
SPONSOR_MODELS = {
    "member": AUTH_USER_MODEL,
    "group":  "groups.Group",
}

# REST Framework Configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",  # Primary auth for Phase 1
        "rest_framework.authentication.SessionAuthentication",        # For Django admin
    ),

    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",  # This allows public access by default
    ],

    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 10,

    # ============================================================================
    # DEFERRED: Filtering and Throttling (Phase 2+)
    # ============================================================================
    # "DEFAULT_FILTER_BACKENDS": [
    #     "django_filters.rest_framework.DjangoFilterBackend",
    #     "rest_framework.filters.OrderingFilter",
    # ],
    #
    # "DEFAULT_THROTTLE_CLASSES": [
    #     "rest_framework.throttling.ScopedRateThrottle",
    # ],
    #
    # "DEFAULT_THROTTLE_RATES": {
    #     "seeds_list_create": "120/min",
    #     "seeds_detail": "180/min",
    #     "seeds_promote": "30/min",
    #     "seeds_ingest": "60/min",
    # },

}

ACCESS_TOKEN_SIGNING_KEY = os.getenv("ACCESS_TOKEN_SIGNING_KEY", "dev-secret-change-me")

# JWT Settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "SIGNING_KEY": ACCESS_TOKEN_SIGNING_KEY,
     "ALGORITHM": "HS256",
}

SIMPLE_JWT.update({
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
})


# JWT_COOKIE_NAME = os.getenv("JWT_COOKIE_NAME", "refresh_token")
# JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
# JWT_COOKIE_SAMESITE = os.getenv("JWT_COOKIE_SAMESITE", "Lax")

JWT_COOKIE_NAME = os.getenv("JWT_COOKIE_NAME", "refresh_token")
JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "false").lower() in ("1","true","yes")
JWT_COOKIE_SAMESITE = os.getenv("JWT_COOKIE_SAMESITE", "Lax")  # "Lax" locally

SERVICE_JWT_SECRET = os.getenv("SERVICE_JWT_SECRET")
SERVICE_JWT_ALG = os.getenv("SERVICE_JWT_ALG", "HS256")
SERVICE_JWT_ISS = os.getenv("SERVICE_JWT_ISS", "mixtape")
SERVICE_JWT_AUD = os.getenv("SERVICE_JWT_AUD", "django-api")
SERVICE_JWT_TTL_SECONDS = int(os.getenv("SERVICE_JWT_TTL_SECONDS", "600"))

LIVEWIRE_JWT_SECRET = os.getenv("LIVEWIRE_JWT_SECRET")
LIVEWIRE_JWT_ALG = os.getenv("LIVEWIRE_JWT_ALG", "HS256")
LIVEWIRE_JWT_ISS = os.getenv("LIVEWIRE_JWT_ISS", "mixtape")
LIVEWIRE_JWT_AUD = os.getenv("LIVEWIRE_JWT_AUD", "livewire")

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


#Email Configuration
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "in-v3.mailjet.com"
EMAIL_PORT = "587"
EMAIL_HOST_USER = "REDACTED-MAILJET-API-KEY"
EMAIL_HOST_PASSWORD = "REDACTED-MAILJET-SECRET-KEY"
EMAIL_USE_TLS = True


# CORS defaults (safe for local dev)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3010",    # ← Mixtape Release Frontend (Phase 1)
    "http://localhost:4200",
    "http://localhost:8081",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3010",    # ← Mixtape Release Frontend (Phase 1)
    "http://127.0.0.1:4200",
    "http://127.0.0.1:8081",
    "http://localhost:8011",
    "http://127.0.0.1:8011",

]



# # CORS
# CORS_ORIGIN_ALLOW_ALL = False
# CORS_ALLOW_CREDENTIALS = True

# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000",
#     "http://localhost:3001",
#     "http://localhost:4200",
#     "http://localhost:8081",
#     "http://127.0.0.1:4200",
#     "http://127.0.0.1:3000",
#     "http://127.0.0.1:19006",
#     "https://crossroads-dashboard.vercel.app",
# ]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# CSRF_TRUSTED_ORIGINS = [
#     "http://localhost:3000",
#     "http://localhost:3001",
#     "http://localhost:4200",
#     "http://localhost:8081",
#     "http://127.0.0.1:4200",
#     "http://127.0.0.1:3000",
#     "http://127.0.0.1:19006",
#     'https://crossroads.network',
#     'https://api.crossroads.network',
#     'https://crossroads-dashboard.vercel.app/',
# ]




LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Your app loggers
        "activity": {
            "handlers": ["console"],
            "level": "WARNING",  # Will show WARNING and above
            "propagate": False,
        },
        "accounts": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}




"""
Django settings for mixtape project.

Generated by 'django-admin startproject' using Django 4.2.3.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""






