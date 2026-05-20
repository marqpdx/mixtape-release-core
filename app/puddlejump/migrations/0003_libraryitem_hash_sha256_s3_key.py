from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('puddlejump', '0002_rename_puddlejump_library_order_idx_puddlejump__library_d7b6ba_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='libraryitem',
            name='hash_sha256',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='libraryitem',
            name='s3_key',
            field=models.TextField(blank=True),
        ),
    ]
