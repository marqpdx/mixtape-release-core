# usage:
# python manage.py reset_startup_locks

from pathlib import Path

from django.core.management.base import BaseCommand


LOCK_DIR = Path("/tmp/cdoc_locks")


class Command(BaseCommand):
    help = "Removes all startup lock files (forces re-runs on next startup)"

    def handle(self, *args, **options):
        if not LOCK_DIR.exists():
            self.stdout.write("No lock directory found — nothing to remove.")
            return

        lockfiles = list(LOCK_DIR.glob("*.lock"))
        if not lockfiles:
            self.stdout.write("✅ No lock files to remove.")
            return

        for file in lockfiles:
            try:
                file.unlink()
                self.stdout.write(f"🧹 Removed lock: {file}")
            except Exception as e:
                self.stderr.write(f"❌ Failed to remove {file}: {e}")

        self.stdout.write(f"\n✅ Cleanup complete. {len(lockfiles)} lock(s) removed.")
