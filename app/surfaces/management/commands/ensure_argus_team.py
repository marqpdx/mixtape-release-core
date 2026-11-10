# surfaces/management/commands/ensure_argus_team.py
#
# ADR-0064 D5. Idempotent: safe to run at install or any time after. Run
# from the repository root:
#   python3 manage.py ensure_argus_team

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from surfaces.services.argus_team import ensure_argus_team


class Command(BaseCommand):
    help = "Idempotently ensure the Argus Team Group exists (ADR-0064 D5). Site owner is its first member."

    def handle(self, *args, **options):
        User = get_user_model()
        site_owner = User.objects.filter(is_superuser=True).order_by("date_joined").first()
        if site_owner is None:
            raise CommandError("No superuser found to be the Argus Team's site-owner member.")

        group = ensure_argus_team(site_owner=site_owner)
        self.stdout.write(self.style.SUCCESS(f"Argus Team: {group.id} (slug={group.slug})"))
