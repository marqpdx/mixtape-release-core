from django.apps import AppConfig


class InitiativesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "initiatives"
    verbose_name = "Initiatives"

    def ready(self):
        import initiatives.signals  # noqa: F401
