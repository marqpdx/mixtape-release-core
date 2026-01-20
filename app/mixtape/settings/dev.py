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
FRONTEND_URL = "http://127.0.0.1:3011"


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
