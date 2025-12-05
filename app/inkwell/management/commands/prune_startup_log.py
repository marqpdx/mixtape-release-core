from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from inkwell.models import StartupLog


class Command(BaseCommand):
    help = "Deletes startup logs older than N days (default: 30)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=30,
            help="Delete logs older than this many days (default: 30)"
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        old_logs = StartupLog.objects.filter(started_at__lt=cutoff)
        count = old_logs.count()
        old_logs.delete()
        self.stdout.write(f"🧹 Deleted {count} startup log(s) older than {options['days']} days.")
