# Generated manually for External Sources credential storage.

import fundamentals.encrypted_fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sourcework", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="externalconnection",
            name="credential_payload",
            field=fundamentals.encrypted_fields.EncryptedTextField(
                blank=True,
                default="",
                help_text="Encrypted provider credential payload. Never expose through agent or public API surfaces.",
            ),
        ),
    ]
