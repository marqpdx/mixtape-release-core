# mixtape-back/mixtape/settings_test.py
from .dev import *


# Override database for testing

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "test.db.sqlite3"),
    }
}

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'mixtape_test',  # Separate test DB
#         'USER': os.getenv('DB_USER'),
#         'PASSWORD': os.getenv('DB_PASSWORD'),
#         'HOST': os.getenv('DB_HOST', 'localhost'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#     }
# }

# Optionally disable some features for faster tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# Disable password hashing for faster user creation (optional)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# CRITICAL: Make Celery run tasks synchronously in-process for tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Use test URLs (if using Option A)
ROOT_URLCONF = "mixtape.urls_test"

# Disable CSRF for test endpoints (already using @csrf_exempt but this helps too)
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Allow all hosts in test
ALLOWED_HOSTS = ["*"]
