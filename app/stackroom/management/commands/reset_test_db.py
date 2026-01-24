from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg2 import sql


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
        db_user = settings.DATABASES.get("default", {}).get("USER", "")
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
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid();
                """,
                [db_name],
            )
            cursor.execute("DROP SCHEMA public CASCADE;")
            cursor.execute("CREATE SCHEMA public;")
            if db_user:
                cursor.execute(
                    sql.SQL("GRANT ALL ON SCHEMA public TO {};").format(
                        sql.Identifier(db_user)
                    )
                )
            cursor.execute("GRANT ALL ON SCHEMA public TO public;")

            extensions = settings.DATABASES.get("default", {}).get(
                "TEST_EXTENSIONS", []
            )
            for extension in extensions:
                cursor.execute(
                    sql.SQL('CREATE EXTENSION IF NOT EXISTS "{}";').format(
                        sql.Identifier(extension)
                    )
                )

        self.stdout.write(self.style.SUCCESS("Test database schema reset."))
