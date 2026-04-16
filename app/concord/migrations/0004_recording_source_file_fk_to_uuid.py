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

    operations = []
