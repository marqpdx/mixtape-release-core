from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("writing", "0033_writingpiece_craft_ignored_dimensions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="writingpiece",
            name="signed_off_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="signed_off_writing_pieces",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
