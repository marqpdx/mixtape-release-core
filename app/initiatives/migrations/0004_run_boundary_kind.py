from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('initiatives', '0003_aperture_log'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aperturelogentry',
            name='kind',
            field=models.CharField(
                choices=[
                    ('prose', 'Prose'),
                    ('ledger', 'Ledger'),
                    ('handoff', 'Handoff'),
                    ('emph', 'Emphasis'),
                    ('seed_spawn', 'Seed Spawn'),
                    ('run_boundary', 'Run Boundary'),
                ],
                default='prose',
                max_length=20,
            ),
        ),
    ]
