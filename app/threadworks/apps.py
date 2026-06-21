from django.apps import AppConfig


class ThreadworksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'threadworks'

    def ready(self):
        import threadworks.stackroom_signals  # noqa: F401
        import threadworks.memory_signals  # noqa: F401
