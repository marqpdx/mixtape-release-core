from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('spellbook', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserDictionaryEntry',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('ignore', 'Ignore'), ('replace', 'Replace')], max_length=16)),
                ('token', models.CharField(db_index=True, max_length=100)),
                ('display', models.CharField(blank=True, default='', max_length=100)),
                ('replacement', models.CharField(blank=True, default='', max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='spell_dictionary_entries_created', to=settings.AUTH_USER_MODEL)),
                ('owner_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='spell_dictionary_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'User Dictionary Entry',
                'verbose_name_plural': 'User Dictionary Entries',
                'ordering': ['token'],
                'unique_together': {('owner_user', 'kind', 'token')},
            },
        ),
    ]
