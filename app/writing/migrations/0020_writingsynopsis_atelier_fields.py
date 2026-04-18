from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0019_alter_leafplacementreaction_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="writingsynopsis",
            name="internal_abstract",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Internal-facing abstract. Oriented toward readers already within Mixtape.",
            ),
        ),
        migrations.AddField(
            model_name="writingsynopsis",
            name="public_synopsis_confirmed",
            field=models.BooleanField(
                default=False,
                help_text="Author has confirmed the public synopsis in Atelier.",
            ),
        ),
        migrations.AddField(
            model_name="writingsynopsis",
            name="linkedin_synopsis_confirmed",
            field=models.BooleanField(
                default=False,
                help_text="Author has confirmed the LinkedIn synopsis in Atelier.",
            ),
        ),
        migrations.AddField(
            model_name="writingsynopsis",
            name="internal_abstract_confirmed",
            field=models.BooleanField(
                default=False,
                help_text="Author has confirmed the internal abstract in Atelier.",
            ),
        ),
    ]
