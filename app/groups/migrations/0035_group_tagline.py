from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0034_presentation_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="tagline",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Display tagline (≤160 chars). Used as the deck on public group pages; summary is reserved for metadata.",
                max_length=160,
            ),
            preserve_default=False,
        ),
    ]
