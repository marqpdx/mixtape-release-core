"""Existing person runtimes, Claude and Codex, gain Ariadne's Inquiry Draft, as new ones do (Heddle CR-01, decision S4)."""

from django.conf import settings
from django.db import migrations

MODE = "ariadne.inquiry_draft"


def _person_runtimes(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    app_label, model = settings.AUTH_USER_MODEL.lower().split(".")
    user_ct = ContentType.objects.filter(app_label=app_label, model=model).first()
    if user_ct is None:
        return []
    runtimes = []
    for name in ("TenantClaudeRuntime", "TenantCodexRuntime"):
        Model = apps.get_model("tenant_runtime", name)
        runtimes.extend(Model.objects.filter(tenant_content_type=user_ct))
    return runtimes


def add_mode(apps, schema_editor):
    for runtime in _person_runtimes(apps):
        modes = list(runtime.allowed_ai_modes or [])
        if MODE not in modes:
            runtime.allowed_ai_modes = modes + [MODE]
            runtime.save(update_fields=["allowed_ai_modes"])


def remove_mode(apps, schema_editor):
    for runtime in _person_runtimes(apps):
        modes = list(runtime.allowed_ai_modes or [])
        if MODE in modes:
            runtime.allowed_ai_modes = [m for m in modes if m != MODE]
            runtime.save(update_fields=["allowed_ai_modes"])


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("tenant_runtime", "0007_person_runtimes_atrium_mode"),
    ]

    operations = [migrations.RunPython(add_mode, remove_mode)]
