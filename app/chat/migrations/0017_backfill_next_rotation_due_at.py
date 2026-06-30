# GPT F-002 (LW-D3 Pass 5): backfill next_rotation_due_at for Ephemeral retention policies
# that exist with a null due timestamp after the 0015 schema migration (which added the
# field nullable but ran no data fix). Without this, any Ephemeral conversation created
# before the serializer fix (8640579) will never trigger client-driven key rotation from
# the normal open path. Values mirror _EPHEMERAL_ROTATION_INTERVALS in serializers.py.
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


_INTERVALS = {
    "1d": timedelta(hours=6),
    "7d": timedelta(hours=42),
    "30d": timedelta(days=7),
    "90d": timedelta(days=7),
    "1y": timedelta(days=7),
}


def backfill_next_rotation_due_at(apps, schema_editor):
    ConversationRetentionPolicy = apps.get_model("chat", "ConversationRetentionPolicy")
    now = timezone.now()
    to_update = []
    qs = ConversationRetentionPolicy.objects.filter(
        conversation__trust_profile="ephemeral",
        enforcement_enabled=True,
        next_rotation_due_at__isnull=True,
    ).exclude(retention_period="indefinite").select_related("conversation")
    for policy in qs:
        interval = _INTERVALS.get(policy.retention_period)
        if interval:
            policy.next_rotation_due_at = now + interval
            to_update.append(policy)
    if to_update:
        ConversationRetentionPolicy.objects.bulk_update(to_update, ["next_rotation_due_at"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0016_lwd3_chatmessage_key_version"),
    ]

    operations = [
        migrations.RunPython(backfill_next_rotation_due_at, noop),
    ]
