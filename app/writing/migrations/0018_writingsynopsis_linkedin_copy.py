from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0017_seeddispatch"),
    ]

    operations = [
        migrations.AddField(
            model_name="writingsynopsis",
            name="linkedin_copy",
            field=models.TextField(
                blank=True,
                default="",
                help_text="AI-generated post copy optimised for LinkedIn (~180–320 chars hook).",
            ),
        ),
        migrations.AddField(
            model_name="writingsynopsis",
            name="linkedin_copy_generated_by",
            field=models.CharField(
                blank=True,
                default="",
                help_text="'ai' once generated; empty until then.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="writingsynopsis",
            name="linkedin_copy_extended",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text="Full Inkwell result: hook, short_synopsis, one_line_takeaway, alt_hook.",
                null=True,
            ),
        ),
    ]
