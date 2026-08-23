from django.apps import AppConfig


class AtriumConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "atrium"
    verbose_name = "Atrium"

    def ready(self):
        import atrium.signals  # noqa: F401 — registers post_save receivers
