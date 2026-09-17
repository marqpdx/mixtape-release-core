from django.apps import AppConfig


class ConsoleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "console"

    def ready(self):
        import console.signals  # noqa: F401 — registers InboxKeeper post_save receiver (K-7)
