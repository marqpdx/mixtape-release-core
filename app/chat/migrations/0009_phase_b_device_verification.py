from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0008_conversationretentionpolicy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="userdevicesession",
            name="verification_fingerprint",
            field=models.CharField(blank=True, max_length=48),
        ),
        migrations.AddField(
            model_name="userdevicesession",
            name="is_trusted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="userdevicesession",
            name="trusted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ParticipantVerification",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="verifications",
                        to="chat.conversation",
                    ),
                ),
                (
                    "verifier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="verifications_given",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "verified_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="verifications_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "verified_device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="verifications",
                        to="chat.userdevicesession",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["conversation", "verifier"], name="chat_pv_conv_verifier_idx"),
                    models.Index(fields=["conversation", "verified_user"], name="chat_pv_conv_verified_idx"),
                ],
            },
        ),
        migrations.AlterUniqueTogether(
            name="participantverification",
            unique_together={("conversation", "verifier", "verified_device")},
        ),
    ]
