from django.apps import AppConfig


class ConcordConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'concord'

    def ready(self):
        # Import signals to register them
        # The bulk_import_completed signal is defined in services/bulk_import.py
        # and can be connected to by other apps for post-import processing
        from concord.services import bulk_import_completed  # noqa: F401
