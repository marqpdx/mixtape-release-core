from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0030_writing_assembly_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="writingseries",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="writing_series",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="writingseries",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="writingseries",
            constraint=models.UniqueConstraint(
                condition=models.Q(group__isnull=False),
                fields=["group", "slug"],
                name="unique_writing_series_group_slug",
            ),
        ),
        migrations.AddConstraint(
            model_name="writingseries",
            constraint=models.UniqueConstraint(
                condition=models.Q(user__isnull=False),
                fields=["user", "slug"],
                name="unique_writing_series_user_slug",
            ),
        ),
    ]
