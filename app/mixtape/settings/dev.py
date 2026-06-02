# mixtape/settings/dev.py

# CRITICAL: Force CPU-only mode for PyTorch BEFORE any imports
# This prevents MPS (Apple GPU) crashes with sentence-transformers
import os
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '0'  # Disable MPS entirely
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # Disable CUDA
os.environ['OMP_NUM_THREADS'] = '4'  # Limit CPU threads

# CRITICAL: Disable tqdm completely to prevent threading crashes
# tqdm monitor threads cause segfaults with PyTorch on Apple Silicon
os.environ['TQDM_DISABLE'] = '1'

import sys
from pathlib import Path
from types import ModuleType

if os.environ.get("MIXTAPE_FAKE_TQDM") == "1":
    # CRITICAL: Inject fake tqdm module BEFORE anything imports it
    # This prevents monitor threads from being created at all
    class FakeTqdm(ModuleType):
        """Fake tqdm module that does nothing."""
        def __init__(self, *args, **kwargs):
            super().__init__('tqdm')

        def tqdm(self, iterable=None, *args, **kwargs):
            """No-op tqdm function."""
            return iterable if iterable is not None else []

        def __call__(self, iterable=None, *args, **kwargs):
            """Allow calling fake tqdm module like a function."""
            return self.tqdm(iterable, *args, **kwargs)

        def __getattr__(self, name):
            """Return self for any attribute access (tqdm.auto, etc)."""
            return self

    # Inject fake modules into sys.modules BEFORE any real imports
    fake_tqdm = FakeTqdm()
    sys.modules['tqdm'] = fake_tqdm
    sys.modules['tqdm.auto'] = fake_tqdm
    sys.modules['tqdm._monitor'] = fake_tqdm
    sys.modules['tqdm.std'] = fake_tqdm

    print("🔧 Injected fake tqdm module to prevent threading crashes")

# Disable tqdm before any imports that might use it
import warnings
warnings.filterwarnings('ignore', module='tqdm')

# Enable crash debugging - dumps full traceback on segfaults/crashes
import faulthandler
faulthandler.enable(file=sys.stderr, all_threads=True)

# Register SIGUSR1 handler for manual crash dumps (kill -USR1 <pid>)
import signal
faulthandler.register(signal.SIGUSR1, all_threads=True)

# Import and apply force_cpu patch immediately (dev only, avoid double-init on autoreload)
if os.environ.get("RUN_MAIN") == "true":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import force_cpu  # noqa: E402
    # Patch torch if already imported, or set up import hook
    if 'torch' in sys.modules:
        force_cpu.patch_torch()

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
    "http://localhost:3011",  # Next.js frontend (alternate port)
    "http://127.0.0.1:3010",
    "http://127.0.0.1:3011",
    "http://127.0.0.1:3020",
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
    # Dev convenience — 8h access tokens. Dev SECRET_KEY fallback means dev tokens
    # are forgeable to anyone with repo access. Never use dev tokens against prod.
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
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
FRONTEND_URL = "http://127.0.0.1:3011"

OPS_APPLICATION_SURFACES = {
    "mixtape-web": {
        "label": "Mixtape Web",
        "surface_type": "nextjs",
        "provider": "local-next",
        "environment": "local",
        "endpoint": "http://127.0.0.1:3011",
        "port": 3011,
        "probe_paths": ["/app/api/help/manifest"],
    },
    "crossroads-web": {
        "label": "Crossroads Web",
        "surface_type": "nextjs",
        "provider": "local-next",
        "environment": "local",
        "endpoint": "http://127.0.0.1:3010",
        "port": 3010,
        "probe_paths": ["/"],
    },
    "django-api": {
        "label": "Django API",
        "surface_type": "api",
        "provider": "runserver",
        "environment": "local",
        "endpoint": "http://127.0.0.1:8010",
        "port": 8010,
        "probe_paths": ["/health/"],
    },
}

OPS_LIVEWIRE_MONITOR = {
    "label": "Livewire",
    "provider": "local-socketio",
    "environment": "local",
    "endpoint": "http://127.0.0.1:5001",
    "port": 5001,
    "probe_path": "/socket.io/?EIO=4&transport=polling",
    "notes": [
        "Probes the Socket.IO polling handshake directly.",
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
