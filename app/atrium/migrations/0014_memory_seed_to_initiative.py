# The memory seed moves from the Dialogue up to its Initiative (CTO, 2026-11-04;
# design-st3b §13). Each Dialogue's non-empty seed is appended to its Initiative's
# InitiativeLog.memory, labelled with the Dialogue's title; the Dialogue's own field
# is left as it was. Reverse is a no-op.

from django.db import migrations


def move(apps, schema_editor):
    Dialogue = apps.get_model("atrium", "Dialogue")
    InitiativeLog = apps.get_model("initiatives", "InitiativeLog")
    for dialogue in Dialogue.objects.exclude(session_context="").exclude(initiative__isnull=True):
        seed = (dialogue.session_context or "").strip()
        if not seed:
            continue
        log, _ = InitiativeLog.objects.get_or_create(initiative_id=dialogue.initiative_id)
        block = f"From the Dialogue \"{dialogue.title or 'Untitled'}\":\n{seed}"
        if block in (log.memory or ""):
            continue
        log.memory = f"{log.memory}\n\n{block}".strip() if log.memory else block
        log.save(update_fields=["memory"])


class Migration(migrations.Migration):
    dependencies = [
        ("atrium", "0013_personal_dialogues_in_initiative_zero"),
        ("initiatives", "0030_initiativelog_memory"),
    ]

    operations = [migrations.RunPython(move, migrations.RunPython.noop)]
