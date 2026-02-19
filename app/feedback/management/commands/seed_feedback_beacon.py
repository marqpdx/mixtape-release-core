from django.core.management.base import BaseCommand

from feedback.models import FeedbackBeacon


class Command(BaseCommand):
    help = "Seed a feedback beacon (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--key", required=True, help="Beacon key, e.g. emblems_v1")
        parser.add_argument("--title", required=True, help="Beacon title")
        parser.add_argument("--body", default="", help="Beacon body markdown")
        parser.add_argument("--feature-context", dest="feature_context", default="", help="Feature context text")
        parser.add_argument("--scope", default=FeedbackBeacon.Scope.GLOBAL, help="Scope: global|route|component")
        parser.add_argument("--route-pattern", dest="route_pattern", default="", help="Optional route pattern")
        parser.add_argument("--inactive", action="store_true", help="Create/update as inactive")

    def handle(self, *args, **options):
        key = options["key"]
        defaults = {
            "title": options["title"],
            "body_markdown": options["body"],
            "feature_context": options["feature_context"],
            "scope": options["scope"],
            "route_pattern": options["route_pattern"],
            "is_active": not options["inactive"],
        }

        beacon, created = FeedbackBeacon.objects.update_or_create(
            key=key,
            defaults=defaults,
        )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} beacon '{beacon.key}'"))
