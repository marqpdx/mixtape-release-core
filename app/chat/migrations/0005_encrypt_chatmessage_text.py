from django.db import migrations

from fundamentals.encrypted_fields import EncryptedTextField


def encrypt_existing_messages(apps, schema_editor):
    from django.conf import settings
    from cryptography.fernet import Fernet, InvalidToken

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        return  # No key configured; skip (pre-prod, no real data to protect)

    f = Fernet(key.encode() if isinstance(key, str) else key)
    ChatMessage = apps.get_model("chat", "ChatMessage")

    for msg in ChatMessage.objects.all():
        if not msg.text:
            continue
        try:
            f.decrypt(msg.text.encode())
            # already encrypted — skip
        except (InvalidToken, Exception):
            msg.text = f.encrypt(msg.text.encode()).decode()
            msg.save(update_fields=["text"])


def noop(apps, schema_editor):
    pass  # irreversible — can't decrypt without knowing which rows were plaintext


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_trust_profile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatmessage",
            name="text",
            field=EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_existing_messages, noop),
    ]
