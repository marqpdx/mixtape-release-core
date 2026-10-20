from django.apps import AppConfig


class ShuttleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shuttle"

    def ready(self):
        from .interpretation import tasks  # noqa: F401 — register bounded worker tasks
