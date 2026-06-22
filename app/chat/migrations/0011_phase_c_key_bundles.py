from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_alter_conversationretentionpolicy_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userdevicesession",
            name="public_key",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="ConversationKeyBundle",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True, default=None)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="key_bundles",
                        to="chat.conversation",
                    ),
                ),
                (
                    "recipient_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="key_bundles",
                        to="chat.userdevicesession",
                    ),
                ),
                ("encrypted_key", models.TextField()),
                ("nonce", models.CharField(max_length=64)),
                ("key_version", models.PositiveSmallIntegerField(default=1)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["conversation", "recipient_device"],
                        name="chat_ckb_conv_device_idx",
                    ),
                ],
            },
        ),
        migrations.AlterUniqueTogether(
            name="conversationkeybundle",
            unique_together={("conversation", "recipient_device", "key_version")},
        ),
    ]
