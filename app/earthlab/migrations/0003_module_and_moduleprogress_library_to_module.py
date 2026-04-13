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
#   2. Remove ModuleProgress.library FK (stackroom.Library)
#   3. Add ModuleProgress.module FK (earthlab.Module) — NOT NULL; safe because table is empty
#   4. Update UniqueConstraint from (enrollment, library) → (enrollment, module)
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
        # 2. Remove the old UniqueConstraint on (enrollment, library)
        migrations.RemoveConstraint(
            model_name='moduleprogress',
            name='unique_module_progress_per_enrollment',
        ),

        # 3. Remove the library FK (stackroom.Library)
        migrations.RemoveField(
            model_name='moduleprogress',
            name='library',
        ),

        # 4. Add the module FK (earthlab.Module)
        #    No default needed — earthlab_moduleprogress table is empty in production.
        migrations.AddField(
            model_name='moduleprogress',
            name='module',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='progress',
                to='earthlab.module',
            ),
            preserve_default=False,
        ),

        # 5. Re-add UniqueConstraint on (enrollment, module)
        migrations.AddConstraint(
            model_name='moduleprogress',
            constraint=models.UniqueConstraint(
                fields=['enrollment', 'module'],
                name='unique_module_progress_per_enrollment',
            ),
        ),
    ]
