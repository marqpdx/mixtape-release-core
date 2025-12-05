# to run:
# python manage.py show_startup_log
# or
# python manage.py show_startup_log --json



import json

from django.core.management.base import BaseCommand

from inkwell.models import StartupLog


class Command(BaseCommand):
    help = "Shows recent startup task runs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of most recent logs to show (default: 5)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON"
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        as_json = options["json"]
        logs = StartupLog.objects.order_by("-started_at")[:limit]

        if not logs:
            self.stdout.write("No startup logs found.")
            return

        if as_json:
            data = [
                {
                    "key": log.key,
                    "started_at": log.started_at.isoformat(),
                    "completed_at": log.completed_at.isoformat() if log.completed_at else None,
                    "status": log.status,
                    "message": log.message,
                }
                for log in logs
            ]
            self.stdout.write(json.dumps(data, indent=2))
        else:
            self.stdout.write(f"\n📄 Last {len(logs)} startup runs:\n")
            for log in logs:
                self.stdout.write(
                    f"[{log.started_at:%Y-%m-%d %H:%M:%S}] "
                    f"{log.key} → {log.status.upper()} "
                    f"(completed: {log.completed_at or '❌ not finished'})"
                )
                if log.message:
                    self.stdout.write(f"    ↳ {log.message.strip()}\n")
