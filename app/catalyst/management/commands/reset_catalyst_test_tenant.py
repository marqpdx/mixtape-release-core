"""
Reset all local test data for a Catalyst tenant.

Deletes in dependency order (PROTECT constraints first), then wipes the
Codex directory from the filesystem. Safe to run repeatedly. Never run
against production — the command aborts if DEBUG=False.

Usage:
    python manage.py reset_catalyst_test_tenant
    python manage.py reset_catalyst_test_tenant --slug=mindful-brilliance --email=info@mindfulbrilliance.com
    python manage.py reset_catalyst_test_tenant --dry-run
"""

import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


SLUG_DEFAULT = "mindful-brilliance"
EMAIL_DEFAULT = "info@mindfulbrilliance.com"


class Command(BaseCommand):
    help = "Reset Catalyst test tenant data (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=SLUG_DEFAULT)
        parser.add_argument("--email", default=EMAIL_DEFAULT)
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError("This command only runs in DEBUG mode.")

        slug = options["slug"]
        email = options["email"]
        dry_run = options["dry_run"]

        self.stdout.write(
            f"\nReset Catalyst test tenant {'(DRY RUN) ' if dry_run else ''}—\n"
            f"  slug:   {slug}\n"
            f"  email:  {email}\n"
        )

        deleted = []
        skipped = []

        # ── 1. Client (PROTECT on Group — must go before Group) ──────────────
        try:
            from business.models import Client
            from groups.models.group import Group
            client_qs = Client.objects.filter(group__slug=slug)
            n = client_qs.count()
            if n:
                if not dry_run:
                    client_qs.delete()
                deleted.append(f"Client ({n})")
            else:
                skipped.append("Client (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Client delete failed: {exc}")

        # ── 2. PublicPage (PROTECT on Group — must go before Group) ──────────
        try:
            from groups.models.public_page import PublicPage
            page_qs = PublicPage.objects.filter(group__slug=slug)
            n = page_qs.count()
            if n:
                if not dry_run:
                    page_qs.delete()
                deleted.append(f"PublicPage ({n})")
            else:
                skipped.append("PublicPage (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] PublicPage delete failed: {exc}")

        # ── 3. WelcomeEmailDraft (explicit; would cascade from prospect) ──────
        try:
            from lanternmail.models import WelcomeEmailDraft
            from prospects.models import BusinessProspect
            draft_qs = WelcomeEmailDraft.objects.filter(prospect__slug=slug)
            n = draft_qs.count()
            if n:
                if not dry_run:
                    draft_qs.delete()
                deleted.append(f"WelcomeEmailDraft ({n})")
            else:
                skipped.append("WelcomeEmailDraft (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] WelcomeEmailDraft delete failed: {exc}")

        # ── 4. Group (CASCADE: memberships, invitations, GroupInvitation, etc.) ─
        try:
            from groups.models.group import Group
            group_qs = Group.objects.filter(slug=slug)
            n = group_qs.count()
            if n:
                if not dry_run:
                    group_qs.delete()
                deleted.append(f"Group + cascade ({n})")
            else:
                skipped.append("Group (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Group delete failed: {exc}")

        # ── 5. BusinessProspect (CASCADE: sessions, responses, notes, insights) ─
        try:
            from prospects.models import BusinessProspect
            prospect_qs = BusinessProspect.objects.filter(slug=slug)
            n = prospect_qs.count()
            if n:
                if not dry_run:
                    prospect_qs.delete()
                deleted.append(f"BusinessProspect + cascade ({n})")
            else:
                skipped.append("BusinessProspect (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] BusinessProspect delete failed: {exc}")

        # ── 6. CustomUser + UserProfile (CASCADE) ────────────────────────────
        try:
            from users.models import CustomUser
            user_qs = CustomUser.objects.filter(email=email)
            n = user_qs.count()
            if n:
                if not dry_run:
                    user_qs.delete()
                deleted.append(f"CustomUser + profile ({n})")
            else:
                skipped.append(f"CustomUser (none with email {email})")
        except Exception as exc:
            self.stderr.write(f"  [warn] CustomUser delete failed: {exc}")

        # ── 7. Codex directory ───────────────────────────────────────────────
        codex_dir = Path(settings.CATALYST_CODEX_ROOT) / slug
        if codex_dir.exists():
            if not dry_run:
                shutil.rmtree(codex_dir)
            deleted.append(f"Codex dir ({codex_dir})")
        else:
            skipped.append(f"Codex dir (not found at {codex_dir})")

        # ── Summary ──────────────────────────────────────────────────────────
        self.stdout.write("")
        if deleted:
            for item in deleted:
                prefix = "  [would delete]" if dry_run else "  [deleted]"
                self.stdout.write(self.style.SUCCESS(f"{prefix} {item}"))
        if skipped:
            for item in skipped:
                self.stdout.write(f"  [skip]    {item}")

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
        else:
            self.stdout.write(self.style.SUCCESS("Reset complete. Ready for a fresh activation cycle."))
            self.stdout.write(
                "\n  Note: If a Stackroom library was created for this group,\n"
                "  it remains in Stackroom (no delete endpoint). It will be\n"
                "  orphaned but harmless — a fresh activation creates a new one.\n"
            )
