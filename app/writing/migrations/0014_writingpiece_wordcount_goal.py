from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0013_writing_series"),
    ]

    operations = [
        migrations.AddField(
            model_name="writingpiece",
            name="target_wordcount",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="Writer's soft word count goal for this piece. Null = no target set.",
            ),
        ),
        migrations.AddField(
            model_name="writingpiece",
            name="suggest_splits",
            field=models.BooleanField(
                default=False,
                help_text="If true and word count exceeds target by ≥15%, trigger AI split suggestion.",
            ),
        ),
    ]
