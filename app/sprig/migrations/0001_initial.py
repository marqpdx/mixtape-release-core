import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Sprig',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sponsor_object_id', models.UUIDField(blank=True, null=True)),
                ('kind', models.CharField(choices=[('text', 'Text'), ('voice', 'Voice')], default='text', max_length=8)),
                ('body', models.TextField(blank=True, default='')),
                ('audio_url', models.CharField(blank=True, default='', help_text='SeaweedFS storage key for the recorded audio clip.', max_length=512)),
                ('audio_duration_seconds', models.IntegerField(blank=True, null=True)),
                ('transcript_text', models.TextField(blank=True, null=True)),
                ('transcript_status', models.CharField(blank=True, choices=[('pending', 'Pending'), ('done', 'Done'), ('failed', 'Failed')], max_length=16, null=True)),
                ('transcript_provider', models.CharField(blank=True, max_length=32, null=True)),
                ('transcript_model', models.CharField(blank=True, max_length=64, null=True)),
                ('transcript_backend', models.CharField(blank=True, max_length=32, null=True)),
                ('transcript_created_at', models.DateTimeField(blank=True, null=True)),
                ('transcript_error', models.TextField(blank=True, null=True)),
                ('status', models.CharField(choices=[('captured', 'Captured'), ('committed', 'Committed'), ('archived', 'Archived')], db_index=True, default='captured', max_length=16)),
                ('source', models.CharField(blank=True, max_length=32, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sprigs', to=settings.AUTH_USER_MODEL)),
                ('sponsor_content_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
            ],
            options={
                'ordering': ['-created_at'],
                'abstract': False,
                'indexes': [
                    models.Index(fields=['author', 'status'], name='sprig_sprig_author__status_idx'),
                    models.Index(fields=['sponsor_content_type', 'sponsor_object_id', 'status'], name='sprig_sprig_sponsor_status_idx'),
                ],
            },
        ),
    ]
