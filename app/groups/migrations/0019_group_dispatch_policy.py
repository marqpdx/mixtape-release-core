from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0018_alter_groupcontext_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='group',
            name='dispatch_policy',
            field=models.CharField(
                choices=[
                    ('cloud_default', 'Cloud-assisted (default)'),
                    ('local_preferred', 'Local-first (approve before cloud)'),
                    ('local_only', 'Local only (regulated mode)'),
                    ('local_strict', 'Strict local (no cloud, ever)'),
                ],
                default='cloud_default',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='group',
            name='local_model_tier',
            field=models.CharField(
                choices=[
                    ('standard', 'Standard (Mistral 7B)'),
                    ('high', 'High (Llama 3 70B)'),
                ],
                default='standard',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='group',
            name='local_verb_overrides',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
