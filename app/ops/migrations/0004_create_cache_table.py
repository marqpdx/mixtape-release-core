from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0003_buildlogentry"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
