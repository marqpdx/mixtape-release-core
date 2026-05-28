from django.apps import AppConfig


class ScrapConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scrap"

    def ready(self):
        import scrap.signals  # noqa: F401
