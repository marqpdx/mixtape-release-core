# Split Place into Location + Place (Shuttle ADR-0058, OQ5, 2026-10-18).
#
# A Location (coordinates, address) outlives and can host many named Places
# over time. No production Place rows exist yet, so this moves straight to
# the final shape rather than a null-then-backfill-then-require sequence.
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tapestry', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('latitude', models.FloatField(blank=True, null=True)),
                ('longitude', models.FloatField(blank=True, null=True)),
                ('address', models.CharField(blank=True, default='', max_length=500)),
            ],
            options={
                'ordering': ['address'],
                'abstract': False,
            },
        ),
        migrations.RemoveField(
            model_name='place',
            name='address',
        ),
        migrations.RemoveField(
            model_name='place',
            name='latitude',
        ),
        migrations.RemoveField(
            model_name='place',
            name='longitude',
        ),
        migrations.AddField(
            model_name='place',
            name='location',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='places', to='tapestry.location'),
            preserve_default=False,
        ),
    ]
