from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0011_phase_c_key_bundles"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversationkeybundle",
            name="ephemeral_public_key",
            field=models.TextField(default=""),
            preserve_default=False,
        ),
    ]
