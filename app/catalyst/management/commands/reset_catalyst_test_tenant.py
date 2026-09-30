"""
Reset all local test data for a Catalyst tenant.

Deletes in dependency order (PROTECT constraints first), then wipes the
Codex directory from the filesystem. Safe to run repeatedly. Never run
against production — the command aborts if DEBUG=False.

The slug argument may be specified multiple times. For each slug the command
also sweeps integer-suffix variants (example-test-tenant-1, -2, etc.). Non-
integer suffixes (example-test-tenant-test) must be named explicitly.

Usage:
    python manage.py reset_catalyst_test_tenant
    python manage.py reset_catalyst_test_tenant --slug=example-test-tenant --slug=example-test-tenant-test
    python manage.py reset_catalyst_test_tenant --email=info@example-test-tenant.com --dry-run
"""

import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


SLUG_DEFAULT = "example-test-tenant"
EMAIL_DEFAULT = "info@example-test-tenant.com"


class Command(BaseCommand):
    help = "Reset Catalyst test tenant data (dev only). --slug may be repeated."

    def add_arguments(self, parser):
        parser.add_argument("--slug", action="append", dest="slugs", metavar="SLUG",
                            help="Tenant slug to reset (repeatable). Defaults to example-test-tenant.")
        parser.add_argument("--email", default=EMAIL_DEFAULT)
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError("This command only runs in DEBUG mode.")

        slugs = options["slugs"] or [SLUG_DEFAULT]
        email = options["email"]
        dry_run = options["dry_run"]

        self.stdout.write(
            f"\nReset Catalyst test tenant(s) {'(DRY RUN) ' if dry_run else ''}—\n"
            f"  slugs:  {slugs}\n"
            f"  email:  {email}\n"
        )

        deleted = []
        skipped = []

        # ── 1. Client (PROTECT on Group — must go before Group) ──────────────
        try:
            from business.models import Client
            from groups.models.group import Group
            client_qs = Client.objects.filter(group__slug__in=slugs)
            n = client_qs.count()
            if n:
                if not dry_run:
                    client_qs.delete()
                deleted.append(f"Client ({n})")
            else:
                skipped.append("Client (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Client delete failed: {exc}")

        import re as _re

        def _slug_variants_q(model, field, slug_list):
            """Return a Q that matches exact slugs plus integer-suffix variants."""
            from django.db.models import Q
            q = Q(**{f"{field}__in": slug_list})
            for s in slug_list:
                q |= Q(**{f"{field}__regex": rf"^{_re.escape(s)}-\d+$"})
            return q

        # ── 2. PublicPage (PROTECT on Group — must go before Group) ──────────
        try:
            from groups.models.public_page import PublicPage
            page_qs = PublicPage.objects.filter(_slug_variants_q(PublicPage, "group__slug", slugs))
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
            draft_qs = WelcomeEmailDraft.objects.filter(_slug_variants_q(WelcomeEmailDraft, "prospect__slug", slugs))
            n = draft_qs.count()
            if n:
                if not dry_run:
                    draft_qs.delete()
                deleted.append(f"WelcomeEmailDraft ({n})")
            else:
                skipped.append("WelcomeEmailDraft (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] WelcomeEmailDraft delete failed: {exc}")

        # ── 4. Group — exact slugs + integer-suffix variants; Catalyst only ───
        try:
            from groups.models.group import Group
            group_qs = Group.objects.filter(
                _slug_variants_q(Group, "slug", slugs)
            ).filter(catalyst_enabled=True)  # never touch non-Catalyst groups
            n = group_qs.count()
            if n:
                found = list(group_qs.values_list("slug", flat=True))
                if not dry_run:
                    group_qs.delete()
                deleted.append(f"Group + cascade ({n}): {found}")
            else:
                skipped.append("Group (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Group delete failed: {exc}")

        # ── 5. BusinessProspect — exact slugs + integer-suffix variants ───────
        try:
            from prospects.models import BusinessProspect
            prospect_qs = BusinessProspect.objects.filter(_slug_variants_q(BusinessProspect, "slug", slugs))
            n = prospect_qs.count()
            if n:
                found = list(prospect_qs.values_list("slug", flat=True))
                if not dry_run:
                    prospect_qs.delete()
                deleted.append(f"BusinessProspect + cascade ({n}): {found}")
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

        # ── 7. Codex directories — all named slugs + integer-suffix variants ──
        codex_root = Path(settings.CATALYST_CODEX_ROOT)
        codex_removed = []
        if codex_root.exists():
            patterns = [_re.compile(rf"^{_re.escape(s)}(-\d+)?$") for s in slugs]
            for entry in codex_root.iterdir():
                if entry.is_dir() and any(p.match(entry.name) for p in patterns):
                    if not dry_run:
                        shutil.rmtree(entry)
                    codex_removed.append(entry.name)
        if codex_removed:
            deleted.append(f"Codex dir(s): {codex_removed}")
        else:
            skipped.append(f"Codex dir (none found under {codex_root})")

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
