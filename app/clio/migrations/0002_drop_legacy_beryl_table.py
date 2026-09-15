# Generated manually 2026-09-15
#
# app/beryl/ was deleted outright as part of the Beryl->Clio rename
# (see puddlejump/decisions/beryl-to-clio-rename-build-plan.md). Its own
# migration history went with it, so nothing would otherwise drop the
# physical beryl_berylstate table in any environment where it was actually
# created (confirmed absent in local dev, but not verifiable here for
# staging/production). This migration does that cleanup, idempotently --
# safe to run whether or not the table ever existed.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clio', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS beryl_berylstate;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
