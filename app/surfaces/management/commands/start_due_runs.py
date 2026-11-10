# surfaces/management/commands/start_due_runs.py
#
# ADR-0064 D9 / build-plan AC-4d, AC-8: the systemd timer's entry point.
# Finds run series whose cadence is due and attempts to start each one via
# AC-5's path to Cass's Switchboard. That path doesn't exist yet -- until
# it does, this reports each due series as not reachable, same as the
# "Run now" stub (zz/api-sketch-argus-surface.md §2), and starts nothing.
# Safe to run on a timer either way: a series that isn't due is left alone,
# and nothing here ever marks a run as started without a real answer from
# Cass.

from django.core.management.base import BaseCommand

from initiatives.services.run_series import due_run_series


class Command(BaseCommand):
    help = "Start any run series whose cadence is due (ADR-0064 D9). Safe to run on a timer."

    def handle(self, *args, **options):
        due = due_run_series()
        if not due:
            self.stdout.write("No run series due.")
            return

        for rs in due:
            # AC-5 (argus.start_run on Cass's Switchboard) doesn't exist yet.
            # Report plainly; never silently skip, never fake a start.
            self.stdout.write(
                self.style.WARNING(
                    f"{rs.block_slug} (series {rs.id}) is due but Cass is not reachable yet (AC-5 pending)."
                )
            )
