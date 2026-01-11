from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Reset test database by dropping and recreating the public schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip interactive confirmation prompt.",
        )

    def handle(self, *args, **options):
        db_name = settings.DATABASES.get("default", {}).get("NAME", "")
        if "test" not in db_name:
            raise CommandError(
                f"Refusing to reset database '{db_name}'. Name must contain 'test'."
            )

        if not options["force"]:
            confirm = input(
                f"Type 'yes' to reset database '{db_name}': "
            ).strip()
            if confirm.lower() != "yes":
                self.stdout.write("Aborted.")
                return

        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE;")
            cursor.execute("CREATE SCHEMA public;")

        self.stdout.write(self.style.SUCCESS("Test database schema reset."))
