from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('threadworks', '0003_forum_audience'),
    ]

    operations = [
        migrations.AddField(
            model_name='discussion',
            name='pinned_nav_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text="Short label used in group nav when this discussion is pinned. Ignored unless status='pinned'.",
                max_length=32,
            ),
        ),
    ]
