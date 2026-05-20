from django.apps import AppConfig


class CurationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'curation'
    verbose_name = 'Curation'

    def ready(self):
        import curation.signals  # noqa: F401
