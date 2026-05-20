import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='Library',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('owner_object_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('slug', models.SlugField(blank=True, max_length=255, null=True, unique=True)),
                ('summary', models.TextField(blank=True)),
                ('body', models.TextField(blank=True)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('owner_content_type', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='contenttypes.contenttype',
                )),
            ],
            options={
                'verbose_name': 'Library',
                'verbose_name_plural': 'Libraries',
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='LibraryItem',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('is_folder', models.BooleanField(default=False)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('folder_path', models.CharField(blank=True, max_length=500)),
                ('tags', models.JSONField(blank=True, default=list)),
                ('notes', models.TextField(blank=True)),
                ('is_featured', models.BooleanField(default=False)),
                ('order_index', models.IntegerField(default=0)),
                ('content_type_str', models.CharField(blank=True, max_length=100)),
                ('content_id', models.UUIDField(blank=True, null=True)),
                ('filename', models.CharField(blank=True, max_length=255)),
                ('size_bytes', models.PositiveIntegerField(blank=True, null=True)),
                ('source_file_id', models.UUIDField(blank=True, null=True)),
                ('latest_version_id', models.UUIDField(blank=True, null=True)),
                ('library', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='puddlejump.library',
                )),
            ],
            options={
                'ordering': ['order_index'],
                'abstract': False,
            },
        ),
        migrations.AddIndex(
            model_name='libraryitem',
            index=models.Index(fields=['library', 'order_index'], name='puddlejump_library_order_idx'),
        ),
        migrations.AddIndex(
            model_name='libraryitem',
            index=models.Index(fields=['library', 'is_folder'], name='puddlejump_library_folder_idx'),
        ),
    ]
