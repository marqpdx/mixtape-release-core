# Personal Dialogues move into each member's Initiative Zero (CTO, 2026-11-04;
# design-st3b §13). A Dialogue with no Initiative and no Group gets the member's
# Personal Initiative (sponsor = the User, is_personal=True) when one exists.
# Reversible as a no-op: the Initiative link stays.

from django.conf import settings
from django.db import migrations


def attach(apps, schema_editor):
    Dialogue = apps.get_model("atrium", "Dialogue")
    Initiative = apps.get_model("initiatives", "Initiative")
    ContentType = apps.get_model("contenttypes", "ContentType")

    app_label, model = settings.AUTH_USER_MODEL.lower().split(".")
    user_ct = ContentType.objects.filter(app_label=app_label, model=model).first()
    if user_ct is None:
        return
    personal = Dialogue.objects.filter(initiative__isnull=True, sponsor_object_id__isnull=True)
    for dialogue in personal.select_related("member"):
        i0 = Initiative.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=dialogue.member.user_id,
            is_personal=True,
            deleted_at__isnull=True,
        ).first()
        if i0 is not None:
            dialogue.initiative = i0
            dialogue.save(update_fields=["initiative"])


class Migration(migrations.Migration):
    dependencies = [
        ("atrium", "0012_checkpoint_entries"),
        ("initiatives", "0029_rename_aperturelog_initiativelog"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(attach, migrations.RunPython.noop)]
