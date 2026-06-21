import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_userdevicesession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationAuditEvent",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(
                    choices=[
                        ("conversation_created", "Conversation Created"),
                        ("participant_joined", "Participant Joined"),
                        ("participant_left", "Participant Left"),
                        ("message_sent", "Message Sent"),
                    ],
                    db_index=True,
                    max_length=32,
                )),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="livewire_audit_events",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("conversation", models.ForeignKey(
                    db_index=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="audit_events",
                    to="chat.conversation",
                )),
            ],
            options={
                "indexes": [
                    models.Index(fields=["conversation", "-created_at"], name="chat_convaud_conv_id_created_idx"),
                    models.Index(fields=["actor", "-created_at"], name="chat_convaud_actor_id_created_idx"),
                ],
            },
        ),
    ]
