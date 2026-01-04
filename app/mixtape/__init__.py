# mixtape/__init__.py
import sys

# Avoid importing Celery app during management commands that don't need it.
if not any(cmd in sys.argv for cmd in ("makemigrations", "migrate")):
    from .celery_app import app as celery_app
    __all__ = ("celery_app",)
else:
    __all__ = tuple()

