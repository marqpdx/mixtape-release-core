from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atrium", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="atriumsession",
            name="dial_mode",
            field=models.CharField(
                choices=[
                    ("expressive", "Expressive"),
                    ("very_focused", "Very Focused"),
                    ("vague", "Vague"),
                ],
                default="expressive",
                help_text="The Dial anchor for this session — governs AI posture.",
                max_length=16,
            ),
        ),
    ]
