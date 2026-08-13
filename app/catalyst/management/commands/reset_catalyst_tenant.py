"""
Reset Catalyst tenant data for a re-activation cycle.

Deletes DB records in dependency order and wipes the Codex directory.
Safe to run repeatedly. Works in both DEBUG and production — requires
--confirm to prevent accidents.

Does NOT delete CustomUser/UserProfile — use this on live tenants where
the user account should be preserved.

Usage:
    python manage.py reset_catalyst_tenant --slug=temple-of-belonging --confirm
    python manage.py reset_catalyst_tenant --slug=temple-of-belonging --dry-run
"""

import re
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


SLUG_DEFAULT = "temple-of-belonging"


class Command(BaseCommand):
    help = "Reset Catalyst tenant data for re-activation. Requires --confirm."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default=SLUG_DEFAULT,
            help=f"Tenant slug to reset (default: {SLUG_DEFAULT})",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            default=False,
            help="Required to execute. Omit to do a dry run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be deleted without writing anything.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        slug = options["slug"]
        confirm = options["confirm"]
        dry_run = options["dry_run"]

        if not confirm and not dry_run:
            raise CommandError(
                "Pass --confirm to execute, or --dry-run to preview. "
                "Neither was provided."
            )

        slugs = [slug]

        self.stdout.write(
            f"\nReset Catalyst tenant {'(DRY RUN) ' if dry_run else ''}—\n"
            f"  slug:  {slug}\n"
        )

        deleted = []
        skipped = []

        def _slug_q(field, slug_list):
            from django.db.models import Q
            q = Q(**{f"{field}__in": slug_list})
            for s in slug_list:
                q |= Q(**{f"{field}__regex": rf"^{re.escape(s)}-\d+$"})
            return q

        # ── 1. Client (PROTECT on Group) ──────────────────────────────────────
        try:
            from business.models import Client
            qs = Client.objects.filter(_slug_q("group__slug", slugs))
            n = qs.count()
            if n:
                if not dry_run:
                    qs.delete()
                deleted.append(f"Client ({n})")
            else:
                skipped.append("Client (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Client delete failed: {exc}")

        # ── 2. PublicPage (PROTECT on Group) ──────────────────────────────────
        try:
            from groups.models.public_page import PublicPage
            qs = PublicPage.objects.filter(_slug_q("group__slug", slugs))
            n = qs.count()
            if n:
                if not dry_run:
                    qs.delete()
                deleted.append(f"PublicPage ({n})")
            else:
                skipped.append("PublicPage (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] PublicPage delete failed: {exc}")

        # ── 3. WelcomeEmailDraft ───────────────────────────────────────────────
        try:
            from lanternmail.models import WelcomeEmailDraft
            qs = WelcomeEmailDraft.objects.filter(_slug_q("prospect__slug", slugs))
            n = qs.count()
            if n:
                if not dry_run:
                    qs.delete()
                deleted.append(f"WelcomeEmailDraft ({n})")
            else:
                skipped.append("WelcomeEmailDraft (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] WelcomeEmailDraft delete failed: {exc}")

        # ── 4. Group (catalyst_enabled=True guard — never touch non-Catalyst) ─
        try:
            from groups.models.group import Group
            qs = Group.objects.filter(_slug_q("slug", slugs)).filter(catalyst_enabled=True)
            n = qs.count()
            if n:
                found = list(qs.values_list("slug", flat=True))
                if not dry_run:
                    qs.delete()
                deleted.append(f"Group + cascade ({n}): {found}")
            else:
                skipped.append("Group (none found or not catalyst_enabled)")
        except Exception as exc:
            self.stderr.write(f"  [warn] Group delete failed: {exc}")

        # ── 5. BusinessProspect ───────────────────────────────────────────────
        try:
            from prospects.models import BusinessProspect
            qs = BusinessProspect.objects.filter(_slug_q("slug", slugs))
            n = qs.count()
            if n:
                found = list(qs.values_list("slug", flat=True))
                if not dry_run:
                    qs.delete()
                deleted.append(f"BusinessProspect + cascade ({n}): {found}")
            else:
                skipped.append("BusinessProspect (none found)")
        except Exception as exc:
            self.stderr.write(f"  [warn] BusinessProspect delete failed: {exc}")

        # ── 6. Codex directory ────────────────────────────────────────────────
        codex_root = Path(settings.CATALYST_CODEX_ROOT)
        codex_removed = []
        if codex_root.exists():
            patterns = [re.compile(rf"^{re.escape(s)}(-\d+)?$") for s in slugs]
            for entry in codex_root.iterdir():
                if entry.is_dir() and any(p.match(entry.name) for p in patterns):
                    if not dry_run:
                        shutil.rmtree(entry)
                    codex_removed.append(entry.name)
        if codex_removed:
            deleted.append(f"Codex dir(s): {codex_removed}")
        else:
            skipped.append(f"Codex dir (none found under {codex_root})")

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("")
        for item in deleted:
            prefix = "  [would delete]" if dry_run else "  [deleted]"
            self.stdout.write(self.style.SUCCESS(f"{prefix} {item}"))
        for item in skipped:
            self.stdout.write(f"  [skip]    {item}")

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Reset complete. Ready for a fresh activation cycle.\n\n"
                "  Note: CustomUser records are NOT deleted — user accounts are preserved.\n"
                "  Stackroom library (if created) remains in Qdrant — orphaned but harmless.\n"
                "  Re-run: python manage.py activate_catalyst_tenant --slug=" + slug
            ))
