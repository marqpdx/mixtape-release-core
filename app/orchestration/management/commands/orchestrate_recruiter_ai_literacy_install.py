from django.core.management.base import BaseCommand

from orchestration.specimens.recruiter_ai_literacy import (
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_GROUP_SLUG,
    build_recruiter_ai_literacy_plan,
    execute_recruiter_ai_literacy_install,
)


class Command(BaseCommand):
    help = "Plan or execute the Recruiter AI Literacy Install specimen through governed verbs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--group-slug",
            default=DEFAULT_GROUP_SLUG,
            help=f"Group slug to install into. Defaults to {DEFAULT_GROUP_SLUG}.",
        )
        parser.add_argument(
            "--admin",
            default=DEFAULT_ADMIN_USERNAME,
            help=f"Username to assign as pilot steward/admin. Defaults to {DEFAULT_ADMIN_USERNAME}.",
        )
        parser.add_argument(
            "--draft-course",
            action="store_true",
            help="Seed the EarthLab course as draft instead of published.",
        )
        parser.add_argument(
            "--skip-course",
            action="store_true",
            help="Provision group/discussion only; do not seed EarthLab course.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually execute the Install. Without this flag, only prints the governed-verb plan.",
        )

    def handle(self, *args, **options):
        plan = build_recruiter_ai_literacy_plan(
            group_slug=options["group_slug"],
            admin_username=options["admin"],
        )

        self.stdout.write(self.style.MIGRATE_HEADING(plan.title))
        self.stdout.write(f"Specimen: {plan.specimen_id}")
        self.stdout.write(f"Group:    {plan.group_slug}")
        self.stdout.write(f"Admin:    {plan.admin_username}")
        self.stdout.write("")

        for index, step in enumerate(plan.steps, start=1):
            self.stdout.write(f"{index}. {step.verb_id} — {step.verb_label}")
            self.stdout.write(f"   {step.summary}")
            self.stdout.write(f"   current:  {step.current_state}")
            self.stdout.write(f"   intended: {step.intended_state}")
            self.stdout.write(f"   confirm:  {'yes' if step.requires_confirmation else 'no'}")
            if step.metadata:
                for key, value in step.metadata.items():
                    self.stdout.write(f"   {key}: {value}")

        if not options["execute"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --execute to apply this Install."))
            return

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Executing governed Install specimen..."))
        result = execute_recruiter_ai_literacy_install(
            group_slug=options["group_slug"],
            admin_username=options["admin"],
            draft_course=options["draft_course"],
            skip_course=options["skip_course"],
        )
        self.stdout.write(self.style.SUCCESS("Install execution complete."))
        self.stdout.write(f"ActionRun: {result['action_run_id']}")
