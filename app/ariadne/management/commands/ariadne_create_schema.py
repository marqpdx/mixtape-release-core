"""
Ariadne — P2 Postgres schema isolation (decisions/ariadne/ariadne-build-spec.md §2).

Creates the dedicated Postgres schema Ariadne's eventual tables (P4) will
live in, kept isolated from the main application's `public` schema and
from any other subsystem's tables -- decided 2026-10-09, given the
sensitivity of the corpus (business/strategy docs, security audit
findings). No tables are created here; there's nothing to migrate until
P4's schema exists. This command only reserves the namespace.

Idempotent (`CREATE SCHEMA IF NOT EXISTS`). To reverse:
    DROP SCHEMA IF EXISTS ariadne CASCADE;
(safe today since nothing lives in it yet; not safe once P4 adds tables).
"""

from django.core.management.base import BaseCommand
from django.db import connection

SCHEMA_NAME = "ariadne"


class Command(BaseCommand):
    help = "Create the dedicated Postgres schema for Ariadne (P2, build spec §2). No tables -- reserves the namespace only."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}";')
        self.stdout.write(self.style.SUCCESS(f'Schema "{SCHEMA_NAME}" ready.'))
