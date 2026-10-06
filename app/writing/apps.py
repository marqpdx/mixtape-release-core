from django.apps import AppConfig


class WritingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "writing"

    def ready(self):
        import writing.stackroom_signals  # noqa: F401
        import writing.focus_signals  # noqa: F401
