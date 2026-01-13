# Generated migration for Puddlejump support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stackroom', '0006_remove_libraryitem_unique_library_item_position_and_more'),
    ]

    operations = [
        # Add Puddlejump fields to Library model
        migrations.AddField(
            model_name='library',
            name='puddlejump_bundle_id',
            field=models.CharField(
                max_length=255,
                null=True,
                blank=True,
                db_index=True,
                help_text='UUID from puddlejump.json manifest (if imported from bundle)'
            ),
        ),
        migrations.AddField(
            model_name='library',
            name='puddlejump_origin',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('imported', 'Imported from Puddlejump'),
                    ('created', 'Created in Mixtape')
                ],
                default='created',
                help_text='Whether this collection was imported from a Puddlejump bundle or created in Mixtape'
            ),
        ),
        migrations.AddField(
            model_name='library',
            name='puddlejump_exported_at',
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text='Timestamp of last Puddlejump bundle export'
            ),
        ),

        # Add Puddlejump canonical metadata to LibraryItem model
        migrations.AddField(
            model_name='libraryitem',
            name='puddlejump_canonical_metadata',
            field=models.JSONField(
                default=dict,
                blank=True,
                help_text='Canonical metadata from file front matter (cached): canonical_date, canonical_authority, supersedes, review_date'
            ),
        ),

        # Add index for bundle_id lookups
        migrations.AddIndex(
            model_name='library',
            index=models.Index(fields=['puddlejump_bundle_id'], name='stackroom_l_pdl_bundle_idx'),
        ),
    ]
