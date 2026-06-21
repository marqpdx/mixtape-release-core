# Generated manually — ADR-0047 Phase 1 backend
# Adds: FeedPost, MemoryValueEvent, Forum.is_contained_circle, Discussion
# memory-value + visibility fields, Post quoted-reply + feed_post FK.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('threadworks', '0004_discussion_pinned_nav_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- Forum ---
        migrations.AddField(
            model_name='forum',
            name='is_contained_circle',
            field=models.BooleanField(
                default=False,
                help_text='When True, visibility is Circle-only; one-level-up sharing is not offered (D15).',
            ),
        ),

        # --- Discussion: visibility + memory-value fields ---
        migrations.AddField(
            model_name='discussion',
            name='visibility_scope',
            field=models.CharField(
                choices=[('circle', 'Circle Only'), ('group', 'Group'), ('crossroads', 'Crossroads')],
                default='group',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='discussion',
            name='memory_value_score',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='discussion',
            name='timeliness_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='discussion',
            name='creation_signal',
            field=models.CharField(
                blank=True,
                choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                max_length=6,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='discussion',
            name='summary',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='discussion',
            name='summary_pending',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='discussion',
            name='summary_pending_delta',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Percentage of summary text changed vs. approved summary (0.0–1.0).',
            ),
        ),
        migrations.AddField(
            model_name='discussion',
            name='summary_pending_substantive',
            field=models.BooleanField(
                blank=True,
                null=True,
                help_text='Heuristic flag: True when candidate contains substantive changes beyond the delta.',
            ),
        ),
        migrations.AddField(
            model_name='discussion',
            name='resolution_post',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='threadworks.post',
            ),
        ),
        migrations.AddIndex(
            model_name='discussion',
            index=models.Index(fields=['forum', '-memory_value_score'], name='threadworks_disc_forum_mv_idx'),
        ),

        # --- FeedPost: new model ---
        migrations.CreateModel(
            name='FeedPost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('title', models.CharField(blank=True, max_length=300)),
                ('kind', models.CharField(
                    choices=[('text', 'Text'), ('image', 'Image'), ('link', 'Link'), ('voice', 'Voice')],
                    default='text',
                    max_length=10,
                )),
                ('body_text', models.TextField(blank=True)),
                ('body_json', models.JSONField(blank=True, null=True)),
                ('image_file', models.ImageField(blank=True, null=True, upload_to='feed_posts/images/')),
                ('audio_file', models.FileField(blank=True, null=True, upload_to='feed_posts/audio/')),
                ('link_url', models.URLField(blank=True)),
                ('link_preview', models.JSONField(blank=True, null=True)),
                ('visibility_scope', models.CharField(
                    choices=[('circle', 'Circle Only'), ('group', 'Group'), ('crossroads', 'Crossroads')],
                    default='group',
                    max_length=12,
                )),
                ('memory_value_score', models.FloatField(default=0.0)),
                ('timeliness_date', models.DateField(blank=True, null=True)),
                ('creation_signal', models.CharField(
                    blank=True,
                    choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                    max_length=6,
                    null=True,
                )),
                ('is_deleted', models.BooleanField(default=False)),
                ('author', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='feed_posts',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('forum', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='feed_posts',
                    to='threadworks.forum',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='feedpost',
            index=models.Index(fields=['forum', '-created_at'], name='threadworks_fp_forum_created_idx'),
        ),
        migrations.AddIndex(
            model_name='feedpost',
            index=models.Index(fields=['author', '-created_at'], name='threadworks_fp_author_created_idx'),
        ),
        migrations.AddIndex(
            model_name='feedpost',
            index=models.Index(fields=['forum', '-memory_value_score'], name='threadworks_fp_forum_mv_idx'),
        ),
        migrations.AddIndex(
            model_name='feedpost',
            index=models.Index(fields=['kind', '-created_at'], name='threadworks_fp_kind_created_idx'),
        ),

        # --- Post: make discussion nullable, add feed_post + quoted-reply fields ---
        migrations.AlterField(
            model_name='post',
            name='discussion',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='posts',
                to='threadworks.discussion',
            ),
        ),
        migrations.AddField(
            model_name='post',
            name='feed_post',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='posts',
                to='threadworks.feedpost',
            ),
        ),
        migrations.AddField(
            model_name='post',
            name='quoted_post',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='quotes',
                to='threadworks.post',
            ),
        ),
        migrations.AddField(
            model_name='post',
            name='quoted_passage',
            field=models.TextField(blank=True),
        ),
        migrations.AddIndex(
            model_name='post',
            index=models.Index(fields=['feed_post', 'created_at'], name='threadworks_post_fp_created_idx'),
        ),

        # --- MemoryValueEvent: new append-only event log ---
        migrations.CreateModel(
            name='MemoryValueEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('object_id', models.PositiveBigIntegerField()),
                ('event_type', models.CharField(
                    choices=[
                        ('reaction', 'Reaction'),
                        ('reply', 'Reply'),
                        ('quoted_reply', 'Quoted Reply'),
                        ('author_distinguished_reply', 'Author-Distinguished Reply'),
                        ('creation_signal', 'Creation-Time Signal'),
                        ('moderator_adjustment', 'Moderator Adjustment'),
                        ('summary_approved', 'Summary Approved'),
                    ],
                    max_length=30,
                )),
                ('delta', models.FloatField()),
                ('notes', models.TextField(blank=True)),
                ('actor', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='memory_value_events',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('content_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='contenttypes.contenttype',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='memoryvalueevent',
            index=models.Index(
                fields=['content_type', 'object_id', '-created_at'],
                name='threadworks_mve_ct_obj_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='memoryvalueevent',
            index=models.Index(
                fields=['event_type', '-created_at'],
                name='threadworks_mve_type_created_idx',
            ),
        ),
    ]
