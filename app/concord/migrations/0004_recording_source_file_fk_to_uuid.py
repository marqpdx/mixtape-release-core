# concord/migrations/0004_recording_source_file_fk_to_uuid.py
#
# CR-002 (accepted 2026-04-04): Decouple concord.Recording.source_file FK from
# stackroom.SourceFile. The FK is replaced with a loose UUIDField — the UUID
# value is preserved; only the FK constraint is dropped.
#
# Risk: 🟠 Medium — concord_recording has live production data (transcriptions).
# CTO sign-off: 2026-04-12.
#
# DB change: DROP CONSTRAINT only. Column `source_file_id` (uuid, nullable)
# keeps all existing values. No rows touched. No column renamed. No type cast.
#
# Rollback: reverse_sql is noop — re-adding the FK constraint would require
# every source_file_id to resolve to an existing stackroom_sourcefile row,
# which cannot be guaranteed post-extraction. Manual rollback only if needed.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('concord', '0003_speakeranchor_transcription_transcriptsegment_and_more'),
        # stackroom dependency removed — this migration decouples from it.
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # State operations: update Django's understanding of the schema.
            # No SQL runs for these — SeparateDatabaseAndState skips them in the DB.
            state_operations=[
                migrations.RemoveField(
                    model_name='recording',
                    name='source_file',
                ),
                migrations.AddField(
                    model_name='recording',
                    name='source_file_id',
                    field=models.UUIDField(
                        blank=True,
                        null=True,
                        help_text=(
                            "UUID reference to SourceFile in Stackroom "
                            "(loose — resolved via REST at CP3+)"
                        ),
                    ),
                ),
            ],
            # Database operations: the only real DB change is dropping the FK
            # constraint. The column, its type (uuid), and all values are unchanged.
            database_operations=[
                migrations.RunSQL(
                    sql="""
DO $$
DECLARE
    fk_constraint text;
BEGIN
    SELECT tc.constraint_name
      INTO fk_constraint
      FROM information_schema.table_constraints tc
      JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema   = kcu.table_schema
     WHERE tc.table_name      = 'concord_recording'
       AND tc.constraint_type = 'FOREIGN KEY'
       AND kcu.column_name    = 'source_file_id'
     LIMIT 1;

    IF fk_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE concord_recording DROP CONSTRAINT %I', fk_constraint);
    END IF;
END $$;
""",
                    # Reverse is intentionally a no-op: re-adding the FK constraint
                    # post-extraction is a manual operation requiring data verification.
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
