import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0007_conversationauditevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationRetentionPolicy",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("retention_period", models.CharField(
                    choices=[
                        ("1d", "24 hours"),
                        ("7d", "7 days"),
                        ("30d", "30 days"),
                        ("90d", "90 days"),
                        ("1y", "1 year"),
                        ("indefinite", "Indefinite"),
                    ],
                    default="indefinite",
                    max_length=16,
                )),
                ("enforcement_enabled", models.BooleanField(default=False)),
                ("conversation", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="retention_policy",
                    to="chat.conversation",
                )),
            ],
        ),
    ]
