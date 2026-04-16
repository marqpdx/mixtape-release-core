# earthlab/migrations/0003_module_and_moduleprogress_library_to_module.py
#
# CR-002 (accepted 2026-04-04): Introduce earthlab.Module as EarthLab's owned
# concept; decouple ModuleProgress from stackroom.Library FK.
#
# Risk: 🟡 Low — earthlab_moduleprogress has no production data.
# CTO sign-off: 2026-04-12.
#
# Changes:
#   1. Create earthlab_module table (Module model)
#   2. Create ModuleProgress directly against earthlab.Module
#
# No data migration required — earthlab tables are empty in production.

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('earthlab', '0002_courserun_enrollment_lessonprogress_moduleprogress_and_more'),
        # stackroom dependency removed — Module uses a loose UUID reference instead.
    ]

    operations = [
        # 1. Create the Module model
        migrations.CreateModel(
            name='Module',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(
                    default=uuid.uuid4,
                    editable=False,
                    primary_key=True,
                    serialize=False,
                )),
                ('title', models.CharField(blank=True, default='', max_length=255)),
                ('order_index', models.PositiveIntegerField(default=0)),
                ('library_id', models.UUIDField(
                    blank=True,
                    null=True,
                    help_text='UUID reference to Stackroom Library (loose — resolved via REST at CP3+)',
                )),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='modules',
                    to='earthlab.course',
                )),
            ],
            options={
                'ordering': ['course', 'order_index'],
            },
        ),
        migrations.CreateModel(
            name='ModuleProgress',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('not_started', 'Not Started'), ('in_progress', 'In Progress'), ('completed', 'Completed')], default='not_started', max_length=16)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('enrollment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='module_progress', to='earthlab.enrollment')),
                ('module', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='progress', to='earthlab.module')),
            ],
            options={
                'ordering': ['-updated_at'],
                'constraints': [
                    models.UniqueConstraint(
                        fields=['enrollment', 'module'],
                        name='unique_module_progress_per_enrollment',
                    ),
                ],
                'indexes': [
                    models.Index(fields=['enrollment', 'status'], name='earthlab_mo_enrollm_8f4d9e_idx'),
                ],
            },
        ),
    ]
