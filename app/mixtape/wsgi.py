# wsgi.py

import os

from django.core.wsgi import get_wsgi_application


DJANGO_ENV = os.getenv("DJANGO_ENV", "prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"mixtape.settings.{DJANGO_ENV}")

print("Gunicorn started")
application = get_wsgi_application()
print("🔥 Django app loaded!")
