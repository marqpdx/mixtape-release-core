# mixtape/settings/test.py

from .dev import *

# Override database for testing

# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.sqlite3",
#         "NAME": os.path.join(BASE_DIR, "test.db.sqlite3"),
#     }
# }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "crossroads_test"),
        "USER": os.getenv("DB_USER", "crossroads_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "mixtape_dev_password"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5433"),  # Docker exposes 5433->5432
    }
}

# Optionally disable some features for faster tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# Disable password hashing for faster user creation (optional)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# CRITICAL: Make Celery run tasks synchronously in-process for tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable CSRF for test endpoints (already using @csrf_exempt but this helps too)
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3010", "http://127.0.0.1:3010", "http://localhost:3011", "http://127.0.0.1:3011"]

# Allow all hosts in test
ALLOWED_HOSTS = ["*"]

LISTMONK_BASE_URL = os.getenv("LISTMONK_BASE_URL", "")
LISTMONK_API_USER = os.getenv("LISTMONK_API_USER", "")
LISTMONK_API_TOKEN = os.getenv("LISTMONK_API_TOKEN", "")