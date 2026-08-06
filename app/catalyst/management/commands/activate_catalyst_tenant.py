"""
Activate a BusinessProspect as a Catalyst tenant — Codex provisioning sequence.

Runs activation steps 2–7 (filesystem + git) for a prospect that has already
been converted to a Group via the Django admin action or ProspectConvertView.
Step 1 (IR namespace) and Step 8 (activation email) are not yet wired and are
noted in the output.

Usage:
    python manage.py activate_catalyst_tenant --slug=mindful-brilliance
    python manage.py activate_catalyst_tenant --slug=mindful-brilliance --dry-run
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the Catalyst Codex provisioning sequence for an activated tenant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            required=True,
            help="BusinessProspect slug to activate",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would happen without writing anything",
        )

    def handle(self, *args, **options):
        from django.conf import settings
        from prospects.models import BusinessProspect
        from catalyst.services.activation import CatalystActivationService, CatalystActivationError

        slug = options["slug"]
        dry_run = options["dry_run"]

        try:
            prospect = BusinessProspect.objects.get(slug=slug)
        except BusinessProspect.DoesNotExist:
            raise CommandError(f"No BusinessProspect found with slug '{slug}'.")

        if not prospect.converted_to_group_id:
            raise CommandError(
                f"Prospect '{slug}' has not been converted to a Group yet. "
                "Run the admin action 'Activate as Catalyst client' first."
            )

        codex_root = settings.CATALYST_CODEX_ROOT / slug
        seed_path = getattr(settings, "CATALYST_SEED_PATH", None)

        self.stdout.write(f"\nCatalyst Codex activation {'(DRY RUN) ' if dry_run else ''}—")
        self.stdout.write(f"  prospect:    {prospect.name} ({slug})")
        self.stdout.write(f"  group:       {prospect.converted_to_group}")
        self.stdout.write(f"  codex root:  {codex_root}")
        self.stdout.write(f"  seed path:   {seed_path or '(not set — CATALYST_SEED_PATH missing)'}")
        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        if not seed_path:
            raise CommandError(
                "CATALYST_SEED_PATH is not set. "
                "Add it to your settings pointing at the mixtape-release-catalyst repo root."
            )

        service = CatalystActivationService(prospect)

        try:
            results = service.activate()
        except CatalystActivationError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS("Activation complete."))
        self.stdout.write(f"  Codex root:  {results['codex_root']}")
        self.stdout.write(f"  START-HERE:  {results['docent']}")
        self.stdout.write(f"  IR seeding:  {results['ir']['message']}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "Remaining manual steps:\n"
            "  Step 1 — create Qdrant IR namespace (not yet wired)\n"
            "  Step 8 — send activation email (not yet wired)"
        ))
