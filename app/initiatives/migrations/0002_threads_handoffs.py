"""
0002_threads_handoffs

Full schema pass for Threads, Handoffs, and Initiative status/momentum additions:

Initiative:
  - status: add 'archived' choice
  - status_note: new TextField
  - thread_summaries: new JSONField (parent-held map of thread lane summaries)
  - seeded_from: new FK → Initiative (fork provenance)
  - seeded_at: new DateTimeField (fork timestamp)
  - seed_context: new JSONField (rolling_summary snapshot at fork time)

Session:
  - intent choices updated: exploring→open_inquiry, deciding→decision_session,
    reviewing→focused_review, closing→closing removed, added retrospective + other
  - capture_mode choices updated: text→typed, added pasted

Handoff (new model):
  - kind: blocking / finding / question / note
  - content, from_thread, to_thread, status, resolution, authored_by, etc.
"""

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('initiatives', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ----------------------------------------------------------------
        # Initiative — status: add 'archived' choice
        # ----------------------------------------------------------------
        migrations.AlterField(
            model_name='initiative',
            name='status',
            field=models.CharField(
                choices=[
                    ('active', 'Active'),
                    ('simmering', 'Simmering'),
                    ('paused', 'Paused'),
                    ('resolved', 'Resolved'),
                    ('archived', 'Archived'),
                ],
                default='active',
                max_length=20,
            ),
        ),

        # ----------------------------------------------------------------
        # Initiative — status_note
        # ----------------------------------------------------------------
        migrations.AddField(
            model_name='initiative',
            name='status_note',
            field=models.TextField(
                blank=True,
                default='',
                help_text=(
                    'Optional note explaining the current status — e.g. why archived or paused. '
                    'Not auto-cleared on status change; managed manually.'
                ),
            ),
        ),

        # ----------------------------------------------------------------
        # Initiative — thread_summaries
        # ----------------------------------------------------------------
        migrations.AddField(
            model_name='initiative',
            name='thread_summaries',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    'Map of thread_id → summary object. On parent Initiatives only. '
                    'Schema: {<uuid>: {label, current_direction, key_findings, open_questions, last_updated}}'
                ),
            ),
        ),

        # ----------------------------------------------------------------
        # Initiative — seeded_from (fork provenance FK)
        # ----------------------------------------------------------------
        migrations.AddField(
            model_name='initiative',
            name='seeded_from',
            field=models.ForeignKey(
                blank=True,
                help_text='Source Initiative this was forked from. Read-only after creation.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='forks',
                to='initiatives.initiative',
            ),
        ),

        # ----------------------------------------------------------------
        # Initiative — seeded_at
        # ----------------------------------------------------------------
        migrations.AddField(
            model_name='initiative',
            name='seeded_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp of the fork.',
            ),
        ),

        # ----------------------------------------------------------------
        # Initiative — seed_context
        # ----------------------------------------------------------------
        migrations.AddField(
            model_name='initiative',
            name='seed_context',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text="Snapshot of the source Initiative's rolling_summary at fork time.",
            ),
        ),

        # ----------------------------------------------------------------
        # Session — intent choices (align with spec)
        # ----------------------------------------------------------------
        migrations.AlterField(
            model_name='session',
            name='intent',
            field=models.CharField(
                choices=[
                    ('open_inquiry', 'Open Inquiry'),
                    ('focused_review', 'Focused Review'),
                    ('decision_session', 'Decision Session'),
                    ('retrospective', 'Retrospective'),
                    ('other', 'Other'),
                ],
                default='open_inquiry',
                max_length=20,
            ),
        ),

        # ----------------------------------------------------------------
        # Session — capture_mode choices (align with spec)
        # ----------------------------------------------------------------
        migrations.AlterField(
            model_name='session',
            name='capture_mode',
            field=models.CharField(
                choices=[
                    ('typed', 'Typed'),
                    ('voice', 'Voice'),
                    ('imported', 'Imported'),
                    ('pasted', 'Pasted'),
                ],
                default='typed',
                max_length=20,
            ),
        ),

        # ----------------------------------------------------------------
        # Handoff (new model)
        # ----------------------------------------------------------------
        migrations.CreateModel(
            name='Handoff',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, default=None, null=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(
                    choices=[
                        ('blocking', 'Blocking'),
                        ('finding', 'Finding'),
                        ('question', 'Question'),
                        ('note', 'Note'),
                    ],
                    default='blocking',
                    max_length=20,
                )),
                ('content', models.TextField(
                    help_text='The message — blocking condition, finding, question, or note.',
                )),
                ('status', models.CharField(
                    choices=[
                        ('open', 'Open'),
                        ('resolved', 'Resolved'),
                        ('withdrawn', 'Withdrawn'),
                    ],
                    default='open',
                    max_length=20,
                )),
                ('resolution', models.TextField(blank=True, default='')),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_by', models.CharField(blank=True, default='', max_length=150,
                    help_text="Username or 'ai'.")),
                ('authored_by', models.CharField(blank=True, default='', max_length=150,
                    help_text="Username or 'ai' — tracks whether human or AI wrote it.")),
                ('initiative', models.ForeignKey(
                    help_text='Always the root parent Initiative.',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='handoffs',
                    to='initiatives.initiative',
                )),
                ('from_thread', models.ForeignKey(
                    blank=True,
                    help_text='Thread that created this handoff. Null = from root session or human.',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='outgoing_handoffs',
                    to='initiatives.initiative',
                )),
                ('to_thread', models.ForeignKey(
                    blank=True,
                    help_text='Directed at a specific thread. Null = broadcast to all threads.',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='incoming_handoffs',
                    to='initiatives.initiative',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    help_text='Null if AI-authored.',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_handoffs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'abstract': False,
            },
        ),

        # ----------------------------------------------------------------
        # Handoff indexes
        # ----------------------------------------------------------------
        migrations.AddIndex(
            model_name='handoff',
            index=models.Index(fields=['initiative', 'status'], name='initiatives_initiat_fcf744_idx'),
        ),
        migrations.AddIndex(
            model_name='handoff',
            index=models.Index(fields=['initiative', 'kind'], name='initiatives_initiat_363458_idx'),
        ),
        migrations.AddIndex(
            model_name='handoff',
            index=models.Index(fields=['to_thread', 'status'], name='initiatives_to_thre_5ac371_idx'),
        ),
    ]
