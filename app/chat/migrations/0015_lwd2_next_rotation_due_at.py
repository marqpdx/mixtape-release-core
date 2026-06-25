from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0014_chatmessage_audio_key_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversationretentionpolicy",
            name="next_rotation_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
