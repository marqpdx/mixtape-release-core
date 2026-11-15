from django.apps import AppConfig


class FolioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "folio"
    verbose_name = "Folio"

    def ready(self):
        # Application wiring for recognition's Dictionary seam. This enables
        # nothing: the recognition flags are separate and stay off.
        from folio.dictionary.provider import provide
        from folio.interpretation.recognition import register_dictionary_provider

        register_dictionary_provider(provide)
