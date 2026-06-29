from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("threadworks", "0005_phase1_feedpost_memory_value"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="discussion",
            index=models.Index(
                fields=["-updated_at"], name="discussion_updated_at_desc"
            ),
        ),
    ]
