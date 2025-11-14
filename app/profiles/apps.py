# profiles/apps.py

from django.apps import AppConfig

class ProfilesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'profiles'

    # Phase 1: No signals (deleted signals.py)
    # Will add back in Phase 2 for auto-creating profiles on user creation
    # def ready(self):
    #     import profiles.signals