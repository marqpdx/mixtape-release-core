import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('atrium', '0004_atriumsession_pty_pid'),
        ('initiatives', '0021_aperturelog_compact_cadence'),
    ]

    operations = [
        migrations.CreateModel(
            name='Distillate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('body', models.TextField()),
                ('document_type', models.CharField(
                    choices=[
                        ('field-note', 'Field Note'),
                        ('finding', 'Finding'),
                        ('position-paper', 'Position Paper'),
                        ('draft-adr', 'Draft ADR'),
                        ('summary', 'Summary'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=32,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('initiative', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='distillates',
                    to='initiatives.initiative',
                )),
                ('session', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='distillates',
                    to='atrium.atriumsession',
                )),
            ],
            options={
                'verbose_name': 'Distillate',
                'verbose_name_plural': 'Distillates',
                'ordering': ['-created_at'],
            },
        ),
    ]
