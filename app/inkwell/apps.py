# inkwell/apps.py

import os

from django.apps import AppConfig


class InkwellAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inkwell"

    def ready(self):
        if os.environ.get("RUN_AI_STARTUP") == "1":
            from inkwell.tasks.startup import run_startup_task_async
            run_startup_task_async.delay(force=False)
