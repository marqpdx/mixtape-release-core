from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('initiatives', '0020_aperturelog_compact_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='aperturelog',
            name='compact_cadence',
            field=models.CharField(
                choices=[
                    ('light', 'Light — compact at session close only'),
                    ('steady', 'Steady — every 8 turns or 30 min idle'),
                    ('active', 'Active — every 4 turns or 10 min idle'),
                ],
                default='steady',
                help_text='How frequently the Continuous Keeper runs background compaction for this initiative.',
                max_length=8,
            ),
        ),
    ]
