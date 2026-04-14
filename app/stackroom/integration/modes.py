from django.conf import settings


MODE_LOCAL = "local"
MODE_SHADOW = "shadow"
MODE_REMOTE = "remote"
VALID_MODES = {MODE_LOCAL, MODE_SHADOW, MODE_REMOTE}


def get_integration_mode() -> str:
    mode = getattr(settings, "STACKROOM_INTEGRATION_MODE", MODE_LOCAL)
    if mode not in VALID_MODES:
        return MODE_LOCAL
    return mode
