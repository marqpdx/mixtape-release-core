from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0016_alter_actionrun_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="initiative",
            name="narrative",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Authored north-star statement. Never written by the system. Distinct from AI rolling_summary.",
            ),
        ),
        migrations.AddField(
            model_name="initiative",
            name="position",
            field=models.PositiveIntegerField(
                default=0,
                help_text="User-controlled ordering within active/paused radar lists.",
            ),
        ),
        migrations.AddField(
            model_name="initiative",
            name="last_session_note",
            field=models.CharField(
                blank=True,
                default="",
                max_length=500,
                help_text="Manual 'where we left off' note. Never written by the system.",
            ),
        ),
    ]
