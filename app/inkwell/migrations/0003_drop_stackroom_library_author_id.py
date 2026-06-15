from django.db import migrations


_DROP_USER_FKS = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.key_column_usage kcu
        JOIN information_schema.referential_constraints rc
            ON kcu.constraint_name = rc.constraint_name
        JOIN information_schema.table_constraints tc
            ON rc.unique_constraint_name = tc.constraint_name
        WHERE kcu.table_name LIKE 'stackroom_%'
          AND tc.table_name = 'users_customuser'
    LOOP
        EXECUTE 'ALTER TABLE ' || r.table_name || ' DROP COLUMN IF EXISTS ' || r.column_name;
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    """
    Drop all legacy user FK columns from stackroom_library.

    The stackroom app was extracted to a standalone FastAPI service using
    sponsor_type/sponsor_id. Multiple user FK columns (author_id,
    submitted_by_id, etc.) remained in Django's DB and block user deletion.
    """

    dependencies = [
        ("inkwell", "0002_stackroom_sync_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_DROP_USER_FKS,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
