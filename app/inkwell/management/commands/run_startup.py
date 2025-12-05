# To Run:
# python manage.py run_startup

# Or to override the lock:
# python manage.py run_startup --force

from django.core.management.base import BaseCommand

from inkwell.scripts.startup import run_startup_tasks


class Command(BaseCommand):
    help = "Runs the AI startup task (LLM, RAG, ingest, etc)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true", help="Force re-run even if lock exists"
        )

    def handle(self, *args, **options):
        force = options["force"]
        logger.info("[mgmt] Running startup {'with force' if force else 'normally'}...")
        run_startup_tasks(force=force)
