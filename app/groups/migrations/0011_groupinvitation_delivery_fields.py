from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0010_group_is_helper_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupinvitation",
            name="provider",
            field=models.CharField(default="mailjet", max_length=50),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="provider_message_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="last_send_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="last_task_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="last_queued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
