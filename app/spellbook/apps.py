# spellbook/apps.py

from django.apps import AppConfig


class SpellbookConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "spellbook"
    verbose_name = "Spell Dictionary"
