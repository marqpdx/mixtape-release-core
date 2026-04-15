import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('initiatives', '0004_run_boundary_kind'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Reminder',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('body', models.TextField()),
                ('remind_at', models.DateTimeField()),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('acknowledged', 'Acknowledged'),
                        ('snoozed', 'Snoozed'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('snoozed_until', models.DateTimeField(blank=True, null=True)),
                ('initiative', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reminders',
                    to='initiatives.initiative',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reminders',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['remind_at'],
                'abstract': False,
            },
        ),
    ]
