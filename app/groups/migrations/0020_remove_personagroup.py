from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0019_group_dispatch_policy'),
    ]

    operations = [
        migrations.DeleteModel(
            name='PersonaGroup',
        ),
    ]
