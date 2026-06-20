from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0003_chatmessage_voice_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="trust_profile",
            field=models.CharField(
                choices=[
                    ("standard", "Standard"),
                    ("private", "Private"),
                    ("ephemeral", "Ephemeral"),
                ],
                default="standard",
                max_length=16,
            ),
        ),
    ]
